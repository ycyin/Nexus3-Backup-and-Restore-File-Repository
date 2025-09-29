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



async def upload_component(session, repo_url, repo_format, source_filename: Path, source_directory: str) -> bool | None:
    # print(f"Starting upload: {source_filename}")
    
    # Check file type and skip hash/metadata files
    filename = source_filename.name.lower()
    if any(filename.endswith(ext) for ext in ['.md5', '.sha1', '.sha256', '.sha512', '.asc']):
        # print(f"Skipping hash/signature file: {source_filename}")
        return None
    
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
                    return False  # Indicate failure due to missing coordinates
                
                # Check version policy: SNAPSHOT vs RELEASE
                is_snapshot = version.endswith('-SNAPSHOT')
                print(f"Version {version} is {'SNAPSHOT' if is_snapshot else 'RELEASE'}")
                
                # Get the extension from the filename (excluding hash suffixes)
                clean_filename = source_filename.name
                # Remove possible hash suffixes
                for hash_ext in ['.md5', '.sha1', '.sha256', '.sha512']:
                    if clean_filename.lower().endswith(hash_ext):
                        clean_filename = clean_filename[:-len(hash_ext)]
                
                # Extract extension and classifier from filename
                extension = ""
                classifier = ""
                
                # Expected format: artifactId-version[-classifier].extension
                base_pattern = f"^{re.escape(artifact_id)}-{re.escape(version)}"
                match = re.match(f"{base_pattern}(?:-(.*))?\.(.*)$", clean_filename)

                if match:
                    c, e = match.groups()
                    classifier = c if c else ""
                    extension = e if e else ""
                else:
                    # Fallback for filenames that don't match the pattern
                    if "." in clean_filename:
                        extension = clean_filename.split(".")[-1]

                print(f"Final Maven coordinates: groupId={group_id}, artifactId={artifact_id}, version={version}, extension={extension}, classifier='{classifier}'")

                # Add Maven-specific fields
                data.add_field("maven2.groupId", group_id)
                data.add_field("maven2.artifactId", artifact_id)
                data.add_field("maven2.version", version)
                data.add_field("maven2.asset1.extension", extension)

                # Add classifier if it exists
                if classifier:
                    data.add_field("maven2.asset1.classifier", classifier)

                data.add_field(
                    "maven2.asset1",
                    file_handle,
                    filename=source_filename.name,
                    content_type="application/octet-stream",
                )
            except Exception as e:
                print(f"Failed to parse Maven coordinates from POM for {source_filename}: {e}")
                print(f"Skipping upload for {source_filename}")
                return False  # Indicate failure
        else:
            # Use generic fields for other formats
            data.add_field(
                f"{repo_format}.asset",
                file_handle,
                filename=source_filename.name,
                content_type="application/octet-stream",
            )
        
        headers = {"accept": "application/json"}

        try:
            async with session.post(repo_url, data=data, headers=headers) as response:
                if response.status == 204:
                    print(f"Upload {source_filename!r} Successfully!")
                    return True
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
                    return False
        except aiohttp.ClientError as e:
            print(f"Network error during upload of {source_filename!r}: {e}")
            return False


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

    async with aiohttp.ClientSession(auth=auth) as session:
        repo_format = await get_repo_type(nexus_base_url, session, repo_name)
        if not repo_format:
            raise RuntimeError(f"Could not determine repo format for {repo_name!r}.")

        all_files = [p for p in source_path.rglob("*") if p.is_file()]
        hash_files = {f for f in all_files if f.name.lower().endswith(('.md5', '.sha1', '.sha256', '.sha512', '.asc'))}
        asset_files = [f for f in all_files if f not in hash_files]

        # --- File Analysis and Statistics ---
        pom_files = [f for f in asset_files if f.name.lower().endswith('.pom')]
        snapshot_count = sum(1 for f in asset_files if 'snapshot' in f.name.lower())
        print(f"\n{'='*70}")
        typer.secho("FILE ANALYSIS", fg=typer.colors.YELLOW, bold=True)
        print(f"  - Total files found: {len(all_files)}")
        print(f"  - Asset files to upload: {len(asset_files)}")
        print(f"  - Hash files to skip: {len(hash_files)}")
        print(f"  - POM files: {len(pom_files)}")
        print(f"  - SNAPSHOT versions detected: {snapshot_count}")
        if snapshot_count > 0:
            typer.secho("    WARNING: Ensure the target repository's version policy is set to 'SNAPSHOT'.", fg=typer.colors.YELLOW)
        print(f"{'='*70}\n")

        tasks = []
        if repo_format.lower() == "maven2":
            # Group assets by component directory (version-level)
            component_dirs = {p.parent for p in asset_files}
            
            print(f"Found {len(component_dirs)} potential Maven component directories.")
            
            # Track skipped SNAPSHOT components
            skipped_snapshots = []
            valid_components = []

            for comp_dir in component_dirs:
                assets_in_dir = [p for p in asset_files if p.parent == comp_dir]
                if not assets_in_dir:
                    continue

                # Prioritize POM for coordinates
                pom_file = next((p for p in assets_in_dir if p.name.lower().endswith('.pom')), None)
                group_id, artifact_id, version = None, None, None
                if pom_file:
                    group_id, artifact_id, version = parse_pom_file(pom_file)

                # Fallback to path parsing if POM is missing or fails
                if not all([group_id, artifact_id, version]):
                    try:
                        g, a, v, _ = parse_maven_path(assets_in_dir[0], source_directory)
                        group_id = group_id or g
                        artifact_id = artifact_id or a
                        version = version or v
                    except ValueError as e:
                        print(f"Skipping directory {comp_dir} due to parsing error: {e}")
                        continue
                
                if not all([group_id, artifact_id, version]):
                    print(f"Skipping directory {comp_dir}: Could not determine Maven coordinates.")
                    continue

                # Skip SNAPSHOT versions
                if version.endswith('-SNAPSHOT'):
                    skipped_snapshots.append(f"{group_id}:{artifact_id}:{version}")
                    print(f"Skipping SNAPSHOT component: {group_id}:{artifact_id}:{version}")
                    continue
                
                valid_components.append((group_id, artifact_id, version, assets_in_dir))

            # Display summary
            print(f"\n{'='*70}")
            typer.secho("COMPONENT ANALYSIS", fg=typer.colors.YELLOW, bold=True)
            print(f"  - Total component directories: {len(component_dirs)}")
            print(f"  - Valid RELEASE components: {len(valid_components)}")
            print(f"  - Skipped SNAPSHOT components: {len(skipped_snapshots)}")
            if skipped_snapshots:
                print(f"  - Skipped SNAPSHOTs:")
                for snapshot in skipped_snapshots:
                    print(f"    • {snapshot}")
                typer.secho("    NOTE: SNAPSHOT packages require Maven deploy protocol, not REST API.", fg=typer.colors.YELLOW)
            print(f"{'='*70}")
            
            if not valid_components:
                print("No valid RELEASE components to upload.")
                return
            
            input(f"\nUploading {len(valid_components)} RELEASE components. Press Enter to continue...")

            for group_id, artifact_id, version, assets_in_dir in valid_components:
                tasks.append(asyncio.create_task(
                    upload_maven_component_group(session, repo_url, group_id, artifact_id, version, assets_in_dir)
                ))
        else:
            # For other formats, upload one by one
            input(f"Uploading {len(asset_files)} files individually. Press Enter to continue...")
            for asset_path in asset_files:
                tasks.append(asyncio.create_task(
                    upload_generic_component(session, repo_url, repo_format, asset_path)
                ))

        print(f"Created {len(tasks)} upload tasks.")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = sum(1 for r in results if r is True)
        error_count = sum(1 for r in results if r is False or isinstance(r, Exception))
        
        typer.secho("UPLOAD SUMMARY", fg=typer.colors.YELLOW, bold=True)
        print(f"- Upload tasks: {success_count} successful, {error_count} failed.")
        print(f"- Expected to upload: {len(asset_files)} asset files.{len(tasks)} upload tasks.")
        print(f"- Expected to skip: {len(hash_files)} hash files. {len(skipped_snapshots)} SNAPSHOT components.")

async def upload_maven_component_group(session, repo_url, group_id, artifact_id, version, assets):
    print(f"\n=== Uploading RELEASE component: {group_id}:{artifact_id}:{version} ===")
    print(f"All files in this group: {[a.name for a in assets]}")
    
    # Filter out hash files that shouldn't be uploaded as assets
    filtered_assets = []
    for asset in assets:
        filename = asset.name.lower()
        if any(filename.endswith(ext) for ext in ['.md5', '.sha1', '.sha256', '.sha512', '.asc']):
            print(f"Skipping hash file: {asset.name}")
        else:
            filtered_assets.append(asset)
    
    if not filtered_assets:
        print("No assets to upload after filtering hash files")
        return True
        
    print(f"Assets to upload: {[a.name for a in filtered_assets]}")
    
    data = aiohttp.FormData()
    data.add_field("maven2.groupId", group_id)
    data.add_field("maven2.artifactId", artifact_id)
    data.add_field("maven2.version", version)
    
    # Track coordinates to detect duplicates
    coordinates_seen = set()

    for i, asset_path in enumerate(filtered_assets, 1):
        clean_filename = asset_path.name
        extension, classifier = "", ""
        
        # Extract classifier and extension from filename (RELEASE versions only)
        pattern = f"^{re.escape(artifact_id)}-{re.escape(version)}(?:-(.*))?\.(.*)$"
        match = re.match(pattern, clean_filename)
        if match:
            classifier, extension = match.groups()
            classifier = classifier or ""
        else:
            # Fallback parsing
            if '.' in clean_filename:
                parts = clean_filename.rsplit('.', 1)
                extension = parts[1]
                classifier = ""

        # Create coordinate tuple for duplicate detection
        coordinate = (extension, classifier)
        if coordinate in coordinates_seen:
            print(f"WARNING: Duplicate coordinates detected! Asset {i} ({clean_filename}) has same coordinates as previous asset: extension='{extension}', classifier='{classifier}'")
        else:
            coordinates_seen.add(coordinate)
        
        print(f"Asset {i}: {clean_filename} -> extension='{extension}', classifier='{classifier}' (coordinate: {coordinate})")
        
        data.add_field(f"maven2.asset{i}.extension", extension)
        if classifier:
            data.add_field(f"maven2.asset{i}.classifier", classifier)
        
        file_handle = open(asset_path, "rb")
        data.add_field(f"maven2.asset{i}", file_handle, filename=asset_path.name, content_type="application/octet-stream")

    try:
        async with session.post(repo_url, data=data) as response:
            if response.status == 204:
                print(f"Successfully uploaded component {group_id}:{artifact_id}:{version}")
                return True
            else:
                error_text = await response.text()
                print(f"Failed to upload {group_id}:{artifact_id}:{version}. Status: {response.status}, Error: {error_text}")
                return False
    except aiohttp.ClientError as e:
        print(f"Network error uploading {group_id}:{artifact_id}:{version}: {e}")
        return False
    finally:
        for field in data._fields:
            if isinstance(field[2], aiohttp.payload.IOBasePayload):
                field[2].value.close()

async def upload_generic_component(session, repo_url, repo_format, asset_path):
    data = aiohttp.FormData()
    with open(asset_path, "rb") as file_handle:
        data.add_field(f"{repo_format}.asset", file_handle, filename=asset_path.name)
        try:
            async with session.post(repo_url, data=data) as response:
                if response.status == 204:
                    print(f"Successfully uploaded {asset_path.name}")
                    return True
                else:
                    print(f"Failed to upload {asset_path.name}: {response.status}")
                    return False
        except aiohttp.ClientError as e:
            print(f"Network error uploading {asset_path.name}: {e}")
            return False
