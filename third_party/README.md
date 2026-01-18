# third_party 说明

这里存放外部依赖源码（如 `nautilus_trader`、`nautilus_market_maker`）。
为了兼容可能不支持中文路径的构建工具，这里保持 ASCII 目录名。

## 运行环境
`miniforge` 内部写死了绝对路径，移动会导致环境失效，所以保留在仓库根目录。
在 `third_party/运行环境/miniforge` 提供一个快捷入口（软链接）。
