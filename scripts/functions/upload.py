import os
import re
import asyncio
from pathlib import Path
import xml.etree.ElementTree as ET

import aiohttp
import typer


COMPONENTS_ROUTE = "/service/rest/v1/components"
REPOSITORY_ROUTE = "/service/rest/beta/repositories"


def parse_pom_file(pom_path: Path):
    """
    Parses Maven coordinate information from a POM file.
    Handles both namespaced and non-namespaced POM files.
    """
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        
        # Maven POM namespace - handle default namespace
        namespace = {'m': 'http://maven.apache.org/POM/4.0.0'}
        
        # Check if the root element has a namespace
        has_namespace = root.tag.startswith('{http://maven.apache.org/POM/4.0.0}')
        
        def find_text(element_name):
            if has_namespace:
                # Use namespace prefix for namespaced elements
                elem = root.find(f'm:{element_name}', namespace)
                if elem is not None:
                    return elem.text.strip() if elem.text else None
            else:
                # Try without namespace for non-namespaced elements
                elem = root.find(element_name)
                if elem is not None:
                    return elem.text.strip() if elem.text else None
            return None
        
        def find_parent_text(parent_elem, element_name):
            if parent_elem is None:
                return None
            if has_namespace:
                elem = parent_elem.find(f'm:{element_name}', namespace)
            else:
                elem = parent_elem.find(element_name)
            if elem is not None:
                return elem.text.strip() if elem.text else None
            return None
        
        # Get direct elements
        group_id = find_text('groupId')
        artifact_id = find_text('artifactId')
        version = find_text('version')
        
        # If the current POM lacks a groupId or version, try to get it from the parent
        if not group_id or not version:
            if has_namespace:
                parent = root.find('m:parent', namespace)
            else:
                parent = root.find('parent')
                
            if parent is not None:
                if not group_id:
                    parent_group_id = find_parent_text(parent, 'groupId')
                    if parent_group_id:
                        group_id = parent_group_id
                
                if not version:
                    parent_version = find_parent_text(parent, 'version')
                    if parent_version:
                        version = parent_version
        
        print(f"Parsed POM {pom_path.name}: groupId={group_id}, artifactId={artifact_id}, version={version}")
        return group_id, artifact_id, version
    
    except Exception as e:
        print(f"Failed to parse POM file {pom_path}: {e}")
        return None, None, None


def find_pom_file_for_artifact(artifact_path: Path):
    """
    Finds the corresponding POM file for a given artifact file.
    """
    # Get the directory where the file is located
    artifact_dir = artifact_path.parent
    
    # Build possible POM filenames
    artifact_name = artifact_path.name
    
    # Remove the extension and version information to build the base name
    if '.' in artifact_name:
        base_name = artifact_name.split('.')[0]
        # Try to find the corresponding POM file
        possible_pom_names = [
            f"{base_name}.pom",
            # Handle cases with version numbers
        ]
        
        # Also try to find all .pom files in the same directory
        for pom_file in artifact_dir.glob("*.pom"):
            if pom_file.exists():
                return pom_file
    
    return None

def parse_maven_path(file_path: Path, source_directory: str):
    """
    Parse Maven coordinates (groupId, artifactId, version, extension) from a file path
    - The source_directory should be the base path containing the Maven repository structure
    - Supports multi-level groupId
    """

    try:
        relative_path = file_path.relative_to(Path(source_directory))
    except ValueError:
        # If the file is not under source_directory, we cannot parse it
        print(f"Warning: File '{file_path}' is not under source directory '{source_directory}'")
        # Skip
        return None, None, None, None

    parts = list(relative_path.parts)
    print(parts)
    filename = parts[-1]

    if len(parts) < 4:
        raise ValueError(f"Invalid Maven path: {relative_path}")

    version = parts[-2]
    artifact_id = parts[-3]
    group_parts = parts[:-3]
    group_id = ".".join(group_parts) if group_parts else None

    # 文件名解析: artifactId-version[-classifier].ext
    match = re.match(rf"^{artifact_id}-(\d[^-]*)(?:-(.*))?\.(.+)$", filename)
    if not match:
        raise ValueError(f"Filename does not match expected pattern: {filename}")

    version_from_file, classifier, extension = match.groups()

    if version_from_file != version:
        raise ValueError(f"Version mismatch: dir={version}, file={version_from_file}")

    
    print(f"Parsed Maven coordinates:")
    print(f"  groupId: {group_id}")
    print(f"  artifactId: {artifact_id}")
    print(f"  version: {version}")
    print(f"  extension: {extension}")
    
    return group_id, artifact_id, version, extension



async def upload_component(session, repo_url, repo_format, source_filename: Path, source_directory: str):
    # print(f"Starting upload: {source_filename}")
    
    # Check file type and skip hash/metadata files
    filename = source_filename.name.lower()
    if any(filename.endswith(ext) for ext in ['.md5', '.sha1', '.sha256', '.sha512', '.asc']):
        # print(f"Skipping hash/signature file: {source_filename}")
        return
    
    # Use a 'with' statement to ensure the file handle is properly closed
    with open(source_filename, "rb") as file_handle:
        data = aiohttp.FormData()
        
        if repo_format.lower() == "maven2":
            # Maven repositories require specific fields, obtained only from the POM file
            try:
                group_id = None
                artifact_id = None
                version = None
                
                # Get accurate coordinate information only from the POM file
                if source_filename.suffix.lower() == '.pom':
                    # The current file is the POM file
                    group_id, artifact_id, version = parse_pom_file(source_filename)
                    print(f"Parsed from POM file {source_filename}: groupId={group_id}, artifactId={artifact_id}, version={version}")
                else:
                    # Find the corresponding POM file
                    pom_file = find_pom_file_for_artifact(source_filename)
                    if pom_file:
                        group_id, artifact_id, version = parse_pom_file(pom_file)
                        print(f"Parsed from POM file {pom_file}: groupId={group_id}, artifactId={artifact_id}, version={version}")
                    else:
                        print(f"No POM file found for {source_filename}, skipping Maven coordinate parsing")
                
                # If the current file is not a POM file, try to parse the Maven coordinate information from the file path
                if not all([group_id, artifact_id, version]):
                    print(f"Incomplete Maven coordinates from POM: groupId={group_id}, artifactId={artifact_id}, version={version}")
                    path_group_id, path_artifact_id, path_version, _ = parse_maven_path(source_filename, source_directory)
                    group_id = group_id or path_group_id
                    artifact_id = artifact_id or path_artifact_id
                    version = version or path_version

                # Check if complete Maven coordinate information was obtained
                if not all([group_id, artifact_id, version]):
                    print(f"Incomplete Maven coordinates from POM: groupId={group_id}, artifactId={artifact_id}, version={version}")
                    print(f"Skipping upload for {source_filename} - missing required Maven coordinates")
                    return  # Skip uploading this file
                
                # Check version policy: SNAPSHOT vs RELEASE
                is_snapshot = version.endswith('-SNAPSHOT')
                print(f"Version {version} is {'SNAPSHOT' if is_snapshot else 'RELEASE'}")
                
                # Get the extension from the filename (excluding hash suffixes)
                clean_filename = source_filename.name
                # Remove possible hash suffixes
                for hash_ext in ['.md5', '.sha1', '.sha256', '.sha512']:
                    if clean_filename.lower().endswith(hash_ext):
                        clean_filename = clean_filename[:-len(hash_ext)]
                
                if "." in clean_filename:
                    extension = clean_filename.split(".")[-1]
                else:
                    extension = ""
                
                print(f"Final Maven coordinates: groupId={group_id}, artifactId={artifact_id}, version={version}, extension={extension}")
                
                # Add Maven-specific fields
                data.add_field("maven2.groupId", group_id)
                data.add_field("maven2.artifactId", artifact_id)
                data.add_field("maven2.version", version)
                data.add_field("maven2.asset1.extension", extension)
                data.add_field(
                    "maven2.asset1",
                    file_handle,
                    filename=source_filename.name,
                    content_type="application/octet-stream",
                )
            except Exception as e:
                print(f"Failed to parse Maven coordinates from POM for {source_filename}: {e}")
                print(f"Skipping upload for {source_filename}")
                return  # Skip uploading this file
        else:
            # Use generic fields for other formats
            data.add_field(
                f"{repo_format}.asset",
                file_handle,
                filename=source_filename.name,
                content_type="application/octet-stream",
            )
        
        headers = {"accept": "application/json"}

        async with session.post(repo_url, data=data, headers=headers) as response:
            if response.status == 204:
                print(f"Upload {source_filename!r} Successfully!")
            else:
                print(f"Upload failed for {source_filename!r}: {response.status} - {response.reason}")
                # Print response content for debugging
                try:
                    error_text = await response.text()
                    print(f"Error response: {error_text}")
                    
                    # Analyze common error types and provide suggestions
                    if "Version policy mismatch" in error_text:
                        print("  → SOLUTION: This is a SNAPSHOT vs RELEASE repository policy issue.")
                        print("  → Check if you're uploading SNAPSHOT versions to a RELEASE-only repository.")
                    elif "Repository does not allow updating assets" in error_text:
                        print("  → SOLUTION: Target repository is read-only or doesn't allow updates.")
                        print("  → Use a different repository or check repository permissions.")
                    elif "This path is already a hash" in error_text:
                        print("  → SOLUTION: Hash files (.md5, .sha1) should not be uploaded as assets.")
                        print("  → This file should have been skipped - check file filtering logic.")
                    elif response.status == 400:
                        print("  → SOLUTION: Bad request - check Maven coordinates and file format.")
                    elif response.status == 403:
                        print("  → SOLUTION: Permission denied - check authentication and repository access.")
                    elif response.status == 500:
                        print("  → SOLUTION: Server error - check Nexus server logs for details.")
                        
                except Exception as e:
                    print(f"Could not read error response: {e}")


async def get_repo_type(
    nexus_base_url: str,
    session: aiohttp.ClientSession,
    repo_name,
):
    # The beta repositories endpoint returns a list of repositories and may not
    # support GET-by-name. Query the list and filter by name to obtain the
    # repository format.
    repo_url = f"{nexus_base_url}{REPOSITORY_ROUTE}"
    headers = {"accept": "application/json"}
    async with session.get(repo_url, headers=headers) as response:
        if response.status == 200:
            res_json = await response.json()
            # Expecting a list of repository objects with at least: name, format, type, url
            if isinstance(res_json, list):
                for repo in res_json:
                    if repo.get("name") == repo_name:
                        return repo.get("format")
            else:
                # Some older instances may return an object; attempt to locate repository
                # defensively if structure differs.
                repo = None
                if isinstance(res_json, dict):
                    # Try common keys that might hold the list
                    for key in ("items", "data", "results"):
                        items = res_json.get(key)
                        if isinstance(items, list):
                            for r in items:
                                if r.get("name") == repo_name:
                                    repo = r
                                    break
                            if repo:
                                break
                if repo:
                    return repo.get("format")
        else:
            print(f"Failed to fetch repositories from {repo_url}: {response.status} - {response.reason}")
    print(f"Repository {repo_name!r} not found via beta repositories endpoint.")


async def upload_repository_components(
    nexus_base_url: str,
    repo_name: str,
    username: str,
    password: str,
    source_directory: str,
):
    # --- Pre-emptive Path Validation ---
    source_path = Path(source_directory)
    
    # 1. Check if the directory exists
    if not source_path.exists():
        print(f"\n{'='*70}")
        typer.secho("[ERROR] Source directory does not exist!", fg=typer.colors.RED, bold=True)
        typer.secho(f"Path: {source_directory}", fg=typer.colors.RED)
        print(f"{'='*70}\n")
        raise typer.Exit(code=1)
    
    if not source_path.is_dir():
        print(f"\n{'='*70}")
        typer.secho("[ERROR] Source path is not a directory!", fg=typer.colors.RED, bold=True)
        typer.secho(f"Path: {source_directory}", fg=typer.colors.RED)
        print(f"{'='*70}\n")
        raise typer.Exit(code=1)
    
    # 2. Display the path prominently and ask for confirmation
    print(f"\n{'='*70}")
    typer.secho("UPLOAD SOURCE DIRECTORY", fg=typer.colors.YELLOW, bold=True)
    typer.secho(f"{source_directory}", fg=typer.colors.CYAN, bold=True)
    print(f"{'='*70}")
    
    # Provide guidance on expected directory structure
    print("\n📁 Expected directory structure:")
    print("   For Maven repositories:")
    print("     source_directory/")
    print("     └── com/org/net/...")
    print("         └── [groupId path]/")
    print("             └── [artifactId]/")
    print("                 └── [version]/")
    print("                     ├── artifact-version.jar")
    print("                     ├── artifact-version.pom")
    print("                     └── artifact-version-sources.jar")
    print("")
    print("   For other repository types:")
    print("     source_directory/")
    print("     └── [your files and folders]")
    
    # 3. Ask for user confirmation
    confirm = typer.confirm("\nDo you confirm this is the correct source directory to upload from?")
    if not confirm:
        typer.secho("\nUpload cancelled by user.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)

    repo_url = f"{nexus_base_url}{COMPONENTS_ROUTE}?repository={repo_name}"
    auth = aiohttp.BasicAuth(username, password) if username and password else None

    # Create a session and get the repo_format outside the loop for a single confirmation
    async with aiohttp.ClientSession(auth=auth) as session:
        repo_format = await get_repo_type(nexus_base_url, session, repo_name)
        if not repo_format:
            raise RuntimeError(
                f"Could not determine repository format for {repo_name!r} using {REPOSITORY_ROUTE}."
            )
        
        # Collect all files
        all_components = []
        for root, dirs, files in os.walk(source_directory):
            root_path = Path(root)
            component_path_list = [root_path / Path(x) for x in files]
            all_components.extend(component_path_list)
        
        print(f"Total files to upload: {len(all_components)}")
        # print(f"All component paths: {all_components}")
        
        # Analyze file types and version policies
        pom_files = []
        jar_files = []
        hash_files = []
        snapshot_files = []
        release_files = []
        
        for component in all_components:
            filename = component.name.lower()
            if filename.endswith('.pom'):
                pom_files.append(component)
                # Check if it is a SNAPSHOT version
                if 'snapshot' in filename:
                    snapshot_files.append(component)
                else:
                    release_files.append(component)
            elif filename.endswith('.jar'):
                jar_files.append(component)
                if 'snapshot' in filename:
                    snapshot_files.append(component)
                else:
                    release_files.append(component)
            elif any(filename.endswith(ext) for ext in ['.md5', '.sha1', '.sha256', '.sha512', '.asc']):
                hash_files.append(component)
        
        print(f"File analysis:")
        print(f"  POM files: {len(pom_files)}")
        print(f"  JAR files: {len(jar_files)}")
        print(f"  Hash/signature files: {len(hash_files)} (will be skipped)")
        print(f"  SNAPSHOT versions: {len(snapshot_files)}")
        print(f"  RELEASE versions: {len(release_files)}")
        
        if snapshot_files:
            print(f"WARNING: Found SNAPSHOT versions. Make sure target repository accepts SNAPSHOT uploads.")
        
        # Confirm only once
        effective_files = len(all_components) - len(hash_files)
        input(f"$$$ Uploading {effective_files} files to a {repo_format} repo (skipping {len(hash_files)} hash files). $$$\nPlease press Enter to confirm and continue ...")
        
        # Batch upload all files
        tasks = []
        for component in all_components:
            tasks.append(
                asyncio.create_task(
                    upload_component(
                        session,
                        repo_url,
                        repo_format,
                        component,
                        source_directory,
                    )
                )
            )
        
        print(f"Created {len(tasks)} upload tasks")
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check the results
            success_count = 0
            error_count = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"Task {i} failed with exception: {result}")
                    error_count += 1
                else:
                    success_count += 1
            
            print(f"Upload completed: {success_count} successful, {error_count} failed")
        except Exception as e:
            print(f"Batch upload failed: {e}")
            raise
