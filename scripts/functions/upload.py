import os
import re
import asyncio
from pathlib import Path
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import time

import aiohttp
import typer


COMPONENTS_ROUTE = "/service/rest/v1/components"
REPOSITORY_ROUTE = "/service/rest/beta/repositories"


class ProgressTracker:
    """实时进度跟踪器"""
    def __init__(self):
        self.total_files = 0
        self.processed_files = 0
        self.hash_files = 0
        self.snapshot_files = 0
        self.upload_tasks = 0
        self.completed_uploads = 0
        self.failed_uploads = 0
        self.start_time = time.time()
        
    def update_scan_progress(self):
        """更新扫描进度"""
        self.processed_files += 1
        if self.processed_files % 100 == 0:
            elapsed = time.time() - self.start_time
            rate = self.processed_files / elapsed if elapsed > 0 else 0
            print(f"\r📁 Scanned: {self.processed_files} files ({rate:.1f} files/s) | "
                  f"🚫 Hash: {self.hash_files} | 📸 SNAPSHOT: {self.snapshot_files} | "
                  f"📤 Tasks: {self.upload_tasks}", end="", flush=True)
    
    def update_upload_progress(self, success=True):
        """更新上传进度"""
        if success:
            self.completed_uploads += 1
        else:
            self.failed_uploads += 1
        
        total_completed = self.completed_uploads + self.failed_uploads
        if total_completed % 5 == 0 or total_completed == self.upload_tasks:
            progress = (total_completed / self.upload_tasks * 100) if self.upload_tasks > 0 else 0
            print(f"\r📤 Upload Progress: {total_completed}/{self.upload_tasks} ({progress:.1f}%) | "
                  f"✅ Success: {self.completed_uploads} | ❌ Failed: {self.failed_uploads}", 
                  end="", flush=True)
    
    def print_final_summary(self):
        """打印最终统计"""
        elapsed = time.time() - self.start_time
        print(f"\n\n{'='*70}")
        typer.secho("FINAL SUMMARY", fg=typer.colors.YELLOW, bold=True)
        print(f"⏱️  Total time: {elapsed:.2f} seconds")
        print(f"📁 Files processed: {self.processed_files}")
        print(f"📤 Upload tasks created: {self.upload_tasks}")
        print(f"✅ Successful uploads: {self.completed_uploads}")
        print(f"❌ Failed uploads: {self.failed_uploads}")
        print(f"🚫 Hash files skipped: {self.hash_files}")
        print(f"📸 SNAPSHOT files skipped: {self.snapshot_files}")
        if self.upload_tasks > 0:
            success_rate = (self.completed_uploads / self.upload_tasks * 100)
            print(f"📊 Success rate: {success_rate:.1f}%")
        print(f"{'='*70}")


# 全局进度跟踪器
progress = ProgressTracker()


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
        
        # print(f"Parsed POM {pom_path.name}: groupId={group_id}, artifactId={artifact_id}, version={version}")
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

    
    # print(f"Parsed Maven coordinates:")
    # print(f"  groupId: {group_id}")
    # print(f"  artifactId: {artifact_id}")
    # print(f"  version: {version}")
    # print(f"  extension: {extension}")
    
    return group_id, artifact_id, version, extension


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

        print("🚀 Starting streaming scan and upload...")
        
        # 重置全局进度跟踪器
        global progress
        progress = ProgressTracker()
        
        # 并发上传控制
        semaphore = asyncio.Semaphore(5)  # 减少并发数量，避免session过载
        active_tasks = []  # 在外层定义，确保所有分支都能访问
        
        async def upload_with_semaphore(coro):
            """带信号量控制的上传"""
            async with semaphore:
                return await coro
        
        if repo_format.lower() == "maven2":
            # Maven 仓库：使用深度优先搜索，边扫描边上传
            processed_dirs = set()  # 避免重复处理
            
            async def process_directory(dir_path):
                """深度优先处理目录并立即上传"""
                nonlocal active_tasks  # 确保可以访问外层的 active_tasks
                if dir_path in processed_dirs:
                    return
                processed_dirs.add(dir_path)
                
                # 收集当前目录的所有文件
                dir_files = []
                for file_path in dir_path.iterdir():
                    if file_path.is_file():
                        progress.update_scan_progress()
                        
                        filename_lower = file_path.name.lower()
                        
                        # 过滤哈希文件
                        if any(filename_lower.endswith(ext) for ext in ('.md5', '.sha1', '.sha256', '.sha512', '.asc')):
                            progress.hash_files += 1
                            continue
                        
                        dir_files.append(file_path)
                
                # 检查是否为 SNAPSHOT 目录
                if dir_path.name.endswith('-SNAPSHOT'):
                    progress.snapshot_files += len(dir_files)
                    return
                
                # 如果目录有文件，立即创建并启动上传任务
                if dir_files:
                    # 解析组件坐标
                    pom_file = next((p for p in dir_files if p.name.lower().endswith('.pom')), None)
                    group_id, artifact_id, version = None, None, None
                    
                    if pom_file:
                        group_id, artifact_id, version = parse_pom_file(pom_file)

                    # 回退到路径解析
                    if not all([group_id, artifact_id, version]):
                        try:
                            g, a, v, _ = parse_maven_path(dir_files[0], source_directory)
                            group_id = group_id or g
                            artifact_id = artifact_id or a
                            version = version or v
                        except ValueError:
                            pass
                    
                    # 立即启动上传任务
                    if all([group_id, artifact_id, version]) and not version.endswith('-SNAPSHOT'):
                        progress.upload_tasks += 1
                        task = asyncio.create_task(upload_with_semaphore(
                            upload_maven_component_group(session, repo_url, group_id, artifact_id, version, dir_files)
                        ))
                        active_tasks.append(task)
                        
                        # 控制并发任务数量，避免内存过载
                        if len(active_tasks) >= 20:  # 减少并发数量
                            # 等待一些任务完成
                            done, pending = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
                            active_tasks = list(pending)
            
            # 深度优先遍历所有目录
            async def dfs_traverse(current_path):
                """深度优先遍历目录树"""
                try:
                    for item in current_path.iterdir():
                        if item.is_dir():
                            # 先处理当前目录
                            await process_directory(item)
                            # 然后递归处理子目录
                            await dfs_traverse(item)
                except PermissionError:
                    pass
                    
            await dfs_traverse(source_path)
            
            # 等待所有剩余任务完成
            if active_tasks:
                print(f"\n⏳ Waiting for {len(active_tasks)} remaining uploads to complete...")
                try:
                    await asyncio.gather(*active_tasks, return_exceptions=True)
                except Exception as e:
                    print(f"Error waiting for tasks: {e}")
                        
        else:
            # 非 Maven 仓库：边扫描边上传
            async def process_generic_files():
                """处理非 Maven 仓库的文件上传"""
                nonlocal active_tasks
                
                for file_path in source_path.rglob("*"):
                    if not file_path.is_file():
                        continue
                        
                    progress.update_scan_progress()

                    filename_lower = file_path.name.lower()
                    
                    # 过滤哈希文件
                    if any(filename_lower.endswith(ext) for ext in ('.md5', '.sha1', '.sha256', '.sha512', '.asc')):
                        progress.hash_files += 1
                        continue
                    
                    # 立即启动上传任务
                    progress.upload_tasks += 1
                    task = asyncio.create_task(upload_with_semaphore(
                        upload_generic_component(session, repo_url, repo_format, file_path)
                    ))
                    active_tasks.append(task)
                    
                    # 控制并发任务数量
                    if len(active_tasks) >= 20:  # 减少并发数量
                        done, pending = await asyncio.wait(active_tasks, return_when=asyncio.FIRST_COMPLETED)
                        active_tasks = list(pending)
                
                # 等待所有剩余任务完成
                if active_tasks:
                    print(f"\n⏳ Waiting for {len(active_tasks)} remaining uploads to complete...")
                    try:
                        await asyncio.gather(*active_tasks, return_exceptions=True)
                    except Exception as e:
                        print(f"Error waiting for tasks: {e}")
            
            await process_generic_files()
        
        # 确保所有任务都已完成，再关闭session
        print(f"\n🔄 Ensuring all uploads are complete before closing session...")
        
        # 等待一小段时间，让所有任务有机会完成
        await asyncio.sleep(2)
        
        # 检查是否还有活跃的任务
        if active_tasks:
            print(f"⚠️  Still have {len(active_tasks)} active tasks, forcing completion...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*active_tasks, return_exceptions=True),
                    timeout=30  # 最多等待30秒
                )
            except asyncio.TimeoutError:
                print("⚠️  Some tasks timed out, but continuing...")
            except Exception as e:
                print(f"⚠️  Error in final task completion: {e}")
        
        # 打印最终统计
        progress.print_final_summary()
        
        if progress.snapshot_files > 0:
            typer.secho("    NOTE: SNAPSHOT packages require Maven deploy protocol, not REST API.", fg=typer.colors.YELLOW)

async def upload_maven_component_group(session, repo_url, group_id, artifact_id, version, assets):
    global progress
    
    # Filter out hash files that shouldn't be uploaded as assets
    filtered_assets = []
    for asset in assets:
        filename = asset.name.lower()
        if any(filename.endswith(ext) for ext in ['.md5', '.sha1', '.sha256', '.sha512', '.asc']):
            continue
        else:
            filtered_assets.append(asset)
    
    if not filtered_assets:
        progress.update_upload_progress(success=True)
        return True
    
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
            continue  # Skip duplicates silently
        else:
            coordinates_seen.add(coordinate)
        
        data.add_field(f"maven2.asset{i}.extension", extension)
        if classifier:
            data.add_field(f"maven2.asset{i}.classifier", classifier)
        
        file_handle = open(asset_path, "rb")
        data.add_field(f"maven2.asset{i}", file_handle, filename=asset_path.name, content_type="application/octet-stream")

    try:
        async with session.post(repo_url, data=data) as response:
            success = response.status == 204
            if not success:
                # 打印详细的错误信息
                try:
                    error_text = await response.text()
                    print(f"\n❌ Upload failed for {group_id}:{artifact_id}:{version}")
                    print(f"   Status: {response.status} - {response.reason}")
                    print(f"   Error: {error_text}")
                    
                    # 分析常见错误类型并提供解决建议
                    if "Version policy mismatch" in error_text:
                        print(f"   💡 Solution: Check repository version policy (SNAPSHOT vs RELEASE)")
                    elif "Repository does not allow updating assets" in error_text:
                        print(f"   💡 Solution: Repository is read-only or doesn't allow updates")
                    elif response.status == 400:
                        print(f"   💡 Solution: Check Maven coordinates and file format")
                    elif response.status == 401:
                        print(f"   💡 Solution: Check authentication credentials")
                    elif response.status == 403:
                        print(f"   💡 Solution: Check repository permissions")
                    elif response.status == 500:
                        print(f"   💡 Solution: Server error - check Nexus server logs")
                except Exception as e:
                    print(f"\n❌ Upload failed for {group_id}:{artifact_id}:{version}")
                    print(f"   Status: {response.status} - {response.reason}")
                    print(f"   Could not read error response: {e}")
            
            progress.update_upload_progress(success=success)
            return success
    except aiohttp.ClientError as e:
        print(f"\n❌ Network error uploading {group_id}:{artifact_id}:{version}")
        print(f"   Error: {e}")
        print(f"   💡 Solution: Check network connection and Nexus server availability")
        progress.update_upload_progress(success=False)
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error uploading {group_id}:{artifact_id}:{version}")
        print(f"   Error: {e}")
        progress.update_upload_progress(success=False)
        return False
    finally:
        for field in data._fields:
            if isinstance(field[2], aiohttp.payload.IOBasePayload):
                field[2].value.close()

async def upload_generic_component(session, repo_url, repo_format, asset_path):
    global progress
    
    data = aiohttp.FormData()
    with open(asset_path, "rb") as file_handle:
        data.add_field(f"{repo_format}.asset", file_handle, filename=asset_path.name)
        try:
            async with session.post(repo_url, data=data) as response:
                success = response.status == 204
                progress.update_upload_progress(success=success)
                return success
        except aiohttp.ClientError as e:
            progress.update_upload_progress(success=False)
            return False
