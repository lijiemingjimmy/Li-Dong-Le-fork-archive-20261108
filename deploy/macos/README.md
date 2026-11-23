# Apple Silicon macOS（Lima）

此入口在 Mac 上创建专用 ARM64 Ubuntu 虚拟机，由虚拟机中的 Docker 运行 Android 和控制服务。`./ldl-mac` 将命令转发给虚拟机内的 `./ldl`。

## 条件

- Apple Silicon Mac、macOS 13.5 或以上、Lima 2.0 或以上；Intel Mac 不在适配范围内。
- Homebrew、Git 和 Git LFS。默认分配 4 核、4GiB 内存、40GiB 按需分配磁盘。
- 建议预留至少 15GiB 存储空间，并为 macOS 交换文件保留系统盘空间。
- 运行时保持 Mac 唤醒、网络可用；外置盘需要保持连接。

Docker Desktop 不是此入口的依赖。Android 所需的 binderfs、DMA-BUF heap、IPv6 和 4KiB 页由 Ubuntu 内核提供。模板会在**虚拟机内**安装扩展内核模块、加载 `binder_linux` 并配置开机加载。

## 安装和登录

在通过 Git 克隆的仓库根目录执行：

```sh
brew install lima git-lfs
git lfs install --local
git lfs pull
shasum -a 256 -c apks/SHA256SUMS
./ldl-mac init
./ldl-mac install-apks
./ldl-mac compatibility
./ldl-mac open-app
```

`init` 校验 APK、创建 `ldl-macos` 虚拟机、复制源码、检查环境并构建启动容器。遇到同名虚拟机会停止。首次启动需要下载 Ubuntu、Android 和构建依赖；账号登录、运动记录提交、定时任务均需另行操作。

打开 <http://127.0.0.1:6080>，自行完成账号登录，再按主 README 初始化并检查本人作业：

```sh
./ldl-mac setup
./ldl-mac check
./ldl-mac plan
./ldl-mac status
```

应用端口只向 Mac 回环地址转发 6080，禁止其他应用端口的自动转发，包括 ADB；Lima 自身的本地 SSH 管理通道不受该规则约束。6080 被占用时需先解决冲突。自定义端口时须同时调整 Lima 转发配置和虚拟机 `/opt/ldl/.env` 的 `UI_PORT`。

## 启停、更新和恢复

```sh
./ldl-mac stop       # 关闭整台虚拟机，保留数据
./ldl-mac start      # 启动已有虚拟机和容器
./ldl-mac shell      # 进入 /opt/ldl
./ldl-mac compose ps
./ldl-mac compose logs --tail=50
```

源码位于虚拟机 `/opt/ldl`；默认运行数据在 `/opt/ldl-automation-data`，包括 Android 登录态和私有记录。`sync` 仅传输 Git 已跟踪的源码和校验过的 APK，保留虚拟机 `.env` 和运行数据。它会覆盖同名源码文件，因此应先保存虚拟机内的自定义代码。

获取源码更新后：

```sh
git lfs pull
./ldl-mac sync
./ldl-mac compose build
./ldl-mac compose up -d --no-build
./ldl-mac check
```

首次安装中断时保留虚拟机以便排查。用 `limactl shell ldl-macos` 查看 `/var/log/cloud-init-output.log`；修复网络或软件包错误后，通过 `limactl stop ldl-macos`、`limactl start ldl-macos` 重启。依赖就绪后执行 `sync`、`doctor`、`compose build`、`compose up -d --no-build`，再继续 APK 安装。不要删除已有登录态的虚拟机来重试安装。

其他实例名通过 `LDL_LIMA_INSTANCE` 设置，每次调用需保持一致。只接受字母、数字、下划线和连字符；多个实例还需要不同的宿主控制台端口。

## 外置盘

APFS 外置卷可直接用于 `LIMA_HOME`。ExFAT 卷可创建 APFS 稀疏磁盘映像，以支持 Unix 权限、套接字和稀疏文件。以下命令创建新文件，不格式化外置盘；请替换 `/Volumes/YourDisk`：

```sh
mkdir -p /Volumes/YourDisk/LDL
hdiutil create -size 64g -type SPARSEBUNDLE -fs APFS \
  -volname LDLWorkspace /Volumes/YourDisk/LDL/LDLWorkspace.sparsebundle
hdiutil attach /Volumes/YourDisk/LDL/LDLWorkspace.sparsebundle -nobrowse
export LIMA_HOME=/Volumes/LDLWorkspace/lima
mkdir -p "$LIMA_HOME"
```

将仓库克隆到映像中，再执行安装步骤。每次使用都需先挂载映像，并设置相同的 `LIMA_HOME`；不要在未挂载时创建同名路径。

`LIMA_HOME` 只决定虚拟机数据位置。镜像下载缓存仍在 `~/Library/Caches/lima`，不应假定存在 `LIMA_CACHE_HOME` 配置。系统盘空间不足时，可在 **Lima 未运行且无下载任务时**将缓存移到 APFS 映像中，并在原路径建立符号链接；已有数据应先备份，避免覆盖其他实例的缓存。源码传输临时归档受 `TMPDIR` 控制：

```sh
mkdir -p /Volumes/LDLWorkspace/tmp
export TMPDIR=/Volumes/LDLWorkspace/tmp/
```

使用后先执行 `./ldl-mac stop`，再卸载映像并弹出外置盘。备份时关闭虚拟机并保存整个映像，避免只复制源码而遗漏登录态。

## 网络

Lima 可将宿主 `http_proxy` / `https_proxy` 的回环地址转换为虚拟机可达地址。模板将可用代理配置写入虚拟机私有的 `/etc/docker/daemon.json`，供 Docker 拉取镜像；`init` 同时传入构建代理参数。代理凭据和 `.env` 不应提交到 Git。代理变更或停用时，应调整虚拟机 Docker 配置并重启 Docker。

手动重新构建需要代理时，在 `./ldl-mac shell` 中执行：

```sh
sudo docker compose build \
  --build-arg HTTP_PROXY="${http_proxy:-}" \
  --build-arg HTTPS_PROXY="${https_proxy:-}"
```

## 验证范围

Apple Silicon / macOS 15.5 / Lima 2.3.0 / Ubuntu 24.04 ARM64 环境已验证内核条件、容器构建、Android 启动、APK 安装、浏览器显示、本人账号登录及一次提交后的服务端回读。ExFAT 外置盘上的 APFS 稀疏映像也经过验证。该结果不保证其他账号、Mac 型号或未来 Ubuntu/APK 版本可用。

运行 `python3 -m unittest discover -s deploy/macos/tests` 检查启动器，运行 `limactl validate deploy/macos/lima.yaml` 检查模板。脚本测试使用模拟命令，不启动虚拟机、不提交运动记录。
