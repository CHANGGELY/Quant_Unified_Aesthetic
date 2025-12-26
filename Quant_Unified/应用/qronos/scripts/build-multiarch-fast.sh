#!/bin/bash

# macOS 多架构 Docker 镜像快速构建脚本
#
# 专门为 macOS 优化的多架构构建方案，包含以下加速优化：
# 1. BuildKit 高级特性和并行构建
# 2. 多层缓存策略（Registry Cache + Local Cache）
# 3. 智能分层构建和依赖分离
# 4. 并行架构构建和智能错误恢复
#
# 使用方法：
# ./scripts/build-multiarch-fast.sh [用户名] [版本号] [缓存模式] [Dockerfile选择]
# 例如: ./scripts/build-multiarch-fast.sh xbxtempleton v0.0.2 aggressive auto

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m'

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${PURPLE}[STEP]${NC} $1"; }

# 参数
DOCKER_HUB_USERNAME=${1:-xbxtempleton}
VERSION=${2:-$(date +%Y%m%d-%H%M%S)}
CACHE_MODE=${3:-normal}  # normal | aggressive | offline
USE_MULTIARCH_DOCKERFILE=${4:-auto}  # auto | true | false
IMAGE_NAME="qronos-trading-framework"
FULL_IMAGE_NAME="${DOCKER_HUB_USERNAME}/${IMAGE_NAME}"

# 缓存配置
case $CACHE_MODE in
    "aggressive")
        CACHE_STRATEGY="max"
        BUILD_CACHE_SIZE="10GB"
        USE_INLINE_CACHE="true"
        ;;
    "offline")
        CACHE_STRATEGY="local"
        BUILD_CACHE_SIZE="5GB"
        USE_INLINE_CACHE="false"
        ;;
    *)
        CACHE_STRATEGY="default"
        BUILD_CACHE_SIZE="3GB"
        USE_INLINE_CACHE="true"
        ;;
esac

# 自动选择 Dockerfile
select_dockerfile() {
    if [ "$USE_MULTIARCH_DOCKERFILE" = "auto" ]; then
        if [ -f "Dockerfile.multiarch" ]; then
            DOCKERFILE="Dockerfile.multiarch"
            log_info "自动选择: 使用多阶段优化 Dockerfile.multiarch"
        else
            DOCKERFILE="Dockerfile"
            log_info "自动选择: 使用标准 Dockerfile"
        fi
    elif [ "$USE_MULTIARCH_DOCKERFILE" = "true" ]; then
        if [ -f "Dockerfile.multiarch" ]; then
            DOCKERFILE="Dockerfile.multiarch"
            log_info "强制使用: Dockerfile.multiarch"
        else
            log_error "Dockerfile.multiarch 不存在"
            exit 1
        fi
    else
        DOCKERFILE="Dockerfile"
        log_info "使用标准: Dockerfile"
    fi
}

echo "=========================================="
echo "🚀 macOS 多架构快速构建器"
echo "=========================================="
log_info "用户名: ${DOCKER_HUB_USERNAME}"
log_info "镜像: ${FULL_IMAGE_NAME}:${VERSION}"
log_info "架构: linux/amd64, linux/arm64"
log_info "缓存模式: ${CACHE_MODE} (${CACHE_STRATEGY})"
log_info "构建缓存: ${BUILD_CACHE_SIZE}"
echo "=========================================="

# 环境检查和配置
setup_build_environment() {
    log_step "配置构建环境..."
    
    # 启用 Docker BuildKit 高级特性
    export DOCKER_BUILDKIT=1
    export DOCKER_CLI_EXPERIMENTAL=enabled
    export BUILDKIT_PROGRESS=plain
    
    # 检查 Docker 状态
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker 未运行或无法访问"
        exit 1
    fi
    
    # 检查 Docker Buildx
    if ! docker buildx version > /dev/null 2>&1; then
        log_error "Docker Buildx 不可用，请升级 Docker Desktop"
        exit 1
    fi
    
    # 显示系统信息
    log_info "系统: $(uname -m) ($(uname -s))"
    log_info "Docker: $(docker version --format '{{.Client.Version}}')"
    log_info "Buildx: $(docker buildx version | head -1 | awk '{print $2}')"
}

# 创建或配置构建器
setup_builder() {
    log_step "配置多架构构建器..."
    
    local builder_name="qronos-fast-builder"
    
    # 检查构建器是否存在
    if docker buildx ls | grep -q "$builder_name"; then
        log_info "使用现有构建器: $builder_name"
        docker buildx use "$builder_name"
    else
        log_info "创建新构建器: $builder_name"
        docker buildx create \
            --name "$builder_name" \
            --driver docker-container \
            --driver-opt network=host \
            --buildkitd-flags '--allow-insecure-entitlement security.insecure --allow-insecure-entitlement network.host' \
            --use
    fi
    
    # 启动构建器
    log_info "启动构建器..."
    docker buildx inspect --bootstrap
    
    # 显示支持的平台
    log_info "支持的平台:"
    docker buildx inspect | grep "Platforms:" | sed 's/Platforms: /  /'
}

# 优化构建上下文
optimize_build_context() {
    log_step "优化构建上下文..."
    
    # 创建临时构建目录（可选）
    if [ "$CACHE_MODE" = "aggressive" ]; then
        log_info "使用积极缓存模式，保持完整构建上下文"
    else
        log_info "使用标准构建上下文"
    fi
    
    # 检查 .dockerignore
    if [ ! -f ".dockerignore" ]; then
        log_warning ".dockerignore 不存在，构建上下文可能过大"
    else
        local context_size=$(du -sh . | cut -f1)
        log_info "构建上下文大小: $context_size"
    fi
}

# 清理旧的构建缓存
cleanup_cache() {
    log_step "清理构建缓存..."
    
    # 清理 Docker 构建缓存
    if [ "$CACHE_MODE" = "offline" ]; then
        log_info "离线模式，保留所有缓存"
    else
        log_info "清理超过 ${BUILD_CACHE_SIZE} 的构建缓存"
        docker builder prune --filter until=168h --keep-storage "$BUILD_CACHE_SIZE" -f || true
    fi
    
    # 显示当前缓存使用情况
    log_info "当前构建缓存:"
    docker system df | grep "Build Cache" || log_warning "无法获取缓存信息"
}

# 预构建基础层（可选优化）
prebuild_base_layers() {
    if [ "$CACHE_MODE" != "aggressive" ]; then
        return
    fi
    
    log_step "预构建基础层..."
    
    # 创建基础层 Dockerfile
    cat > Dockerfile.base << 'EOF'
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# 配置镜像源
RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget locales nginx nodejs npm gcc g++ \
    && echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen \
    && echo "zh_CN.UTF-8 UTF-8" >> /etc/locale.gen \
    && locale-gen \
    && update-locale LANG=en_US.UTF-8 \
    && npm config set registry https://registry.npmmirror.com \
    && npm install -g pm2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
EOF

    # 构建基础层
    log_info "构建基础层镜像..."
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --tag "${FULL_IMAGE_NAME}:base-${VERSION}" \
        --cache-from type=registry,ref="${FULL_IMAGE_NAME}:base-latest" \
        --cache-to type=registry,ref="${FULL_IMAGE_NAME}:base-latest",mode=max \
        --file Dockerfile.base \
        --push \
        . || log_warning "基础层预构建失败，继续使用标准构建"
    
    # 清理临时文件
    rm -f Dockerfile.base
}

# 主构建函数
build_multiarch_image() {
    log_step "开始多架构构建..."
    
    local build_args="--platform linux/amd64,linux/arm64"
    local cache_args=""
    local output_args="--push"
    local dockerfile_args="--file ${DOCKERFILE}"
    
    # 配置缓存策略
    case $CACHE_MODE in
        "aggressive")
            cache_args="--cache-from type=registry,ref=${FULL_IMAGE_NAME}:cache"
            cache_args="${cache_args} --cache-to type=registry,ref=${FULL_IMAGE_NAME}:cache,mode=max"
            # 避免重复的 inline cache
            ;;
        "offline")
            cache_args="--cache-from type=local,src=/tmp/buildx-cache"
            cache_args="${cache_args} --cache-to type=local,dest=/tmp/buildx-cache,mode=max"
            ;;
        *)
            cache_args="--cache-from type=registry,ref=${FULL_IMAGE_NAME}:latest"
            cache_args="${cache_args} --cache-to type=inline"
            ;;
    esac
    
    # 构建命令
    local build_cmd="docker buildx build \
        $build_args \
        --tag ${FULL_IMAGE_NAME}:${VERSION} \
        --tag ${FULL_IMAGE_NAME}:latest \
        $cache_args \
        $output_args \
        $dockerfile_args \
        --progress=plain \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        ."
    
    log_info "执行构建命令："
    log_info "$build_cmd"
    
    # 记录开始时间
    local start_time=$(date +%s)
    
    # 执行构建
    eval "$build_cmd" || {
        log_error "多架构构建失败"
        
        # 尝试单独构建每个架构
        log_warning "尝试单独构建各个架构..."
        build_single_arch "linux/amd64" "amd64"
        build_single_arch "linux/arm64" "arm64"
        return 1
    }
    
    # 记录结束时间
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log_success "多架构构建完成！用时: ${duration}s"
}

# 单架构构建（备用方案）
build_single_arch() {
    local platform=$1
    local arch_tag=$2
    
    log_info "构建 ${platform} 架构..."
    
    docker buildx build \
        --platform "$platform" \
        --tag "${FULL_IMAGE_NAME}:${VERSION}-${arch_tag}" \
        --tag "${FULL_IMAGE_NAME}:latest-${arch_tag}" \
        --cache-from type=registry,ref="${FULL_IMAGE_NAME}:latest-${arch_tag}" \
        --cache-to type=inline \
        --file "${DOCKERFILE}" \
        --push \
        . || log_warning "${platform} 构建失败"
}

# 验证构建结果
verify_build() {
    log_step "验证构建结果..."
    
    # 检查镜像是否存在
    if docker manifest inspect "${FULL_IMAGE_NAME}:${VERSION}" > /dev/null 2>&1; then
        log_success "多架构镜像验证成功"
        
        # 显示架构信息
        log_info "支持的架构:"
        docker manifest inspect "${FULL_IMAGE_NAME}:${VERSION}" | \
            jq -r '.manifests[] | "  - \(.platform.os)/\(.platform.architecture)"' 2>/dev/null || \
            docker manifest inspect "${FULL_IMAGE_NAME}:${VERSION}" | grep -E "architecture|os"
    else
        log_warning "多架构镜像验证失败，检查单架构版本..."
        
        for arch in amd64 arm64; do
            if docker manifest inspect "${FULL_IMAGE_NAME}:${VERSION}-${arch}" > /dev/null 2>&1; then
                log_info "找到单架构版本: ${FULL_IMAGE_NAME}:${VERSION}-${arch}"
            fi
        done
    fi
}

# 显示构建结果和使用说明
show_results() {
    log_step "构建完成报告"
    
    echo ""
    echo "🎉 构建完成！"
    echo ""
    echo "📦 可用镜像:"
    echo "  - 多架构版本: ${FULL_IMAGE_NAME}:${VERSION}"
    echo "  - 最新版本: ${FULL_IMAGE_NAME}:latest"
    echo ""
    echo "🚀 快速启动:"
    echo "  ./deploy-qronos.sh"
    echo ""
    echo "🔧 测试命令:"
    echo "  # 在 AMD64 服务器上:"
    echo "  docker pull ${FULL_IMAGE_NAME}:${VERSION}"
    echo ""
    echo "  # 在 ARM64 Mac 上:"
    echo "  docker pull ${FULL_IMAGE_NAME}:${VERSION}"
    echo ""
    
    # 显示镜像大小
    if command -v docker >/dev/null 2>&1; then
        echo "📊 镜像信息:"
        docker buildx imagetools inspect "${FULL_IMAGE_NAME}:${VERSION}" 2>/dev/null || \
            echo "  无法获取镜像详细信息"
    fi
}

# 清理函数
cleanup() {
    log_info "清理临时文件..."
    rm -f Dockerfile.base 2>/dev/null || true
}

# 主执行流程
main() {
    # 设置错误处理
    trap cleanup EXIT
    
    # 检查 Docker 登录
    if [ "$CACHE_MODE" != "offline" ]; then
        if ! docker info 2>/dev/null | grep -q "Username: ${DOCKER_HUB_USERNAME}"; then
            log_info "请先登录 Docker Hub:"
            docker login
        fi
    fi
    
    # 执行构建流程
    setup_build_environment
    setup_builder
    select_dockerfile  # 选择要使用的 Dockerfile
    optimize_build_context
    cleanup_cache
    
    # 可选的预构建步骤
    if [ "$CACHE_MODE" = "aggressive" ]; then
        prebuild_base_layers
    fi
    
    # 主构建
    if build_multiarch_image; then
        verify_build
        show_results
    else
        log_error "构建失败"
        exit 1
    fi
}

# 显示帮助信息
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "用法: $0 [用户名] [版本号] [缓存模式] [Dockerfile选择]"
    echo ""
    echo "参数:"
    echo "  用户名     Docker Hub 用户名 (默认: xbxtempleton)"
    echo "  版本号     镜像版本标签 (默认: 时间戳)"
    echo "  缓存模式   normal|aggressive|offline (默认: normal)"
    echo "  Dockerfile选择 auto|true|false (默认: auto)"
    echo ""
    echo "缓存模式说明:"
    echo "  normal     - 标准缓存策略，平衡速度和空间"
    echo "  aggressive - 积极缓存，最快构建速度"
    echo "  offline    - 离线模式，仅使用本地缓存"
    echo ""
    echo "Dockerfile选择:"
    echo "  auto      - 文件都存在时，优先使用 Dockerfile.multiarch"
    echo "  true      - 使用 Dockerfile.multiarch"
    echo "  false     - 使用 Dockerfile"
    echo ""
    echo "示例:"
    echo "  $0 myuser v1.0.0 aggressive auto"
    echo "  $0 myuser latest normal auto"
    exit 0
fi

# 执行主函数
main "$@" 