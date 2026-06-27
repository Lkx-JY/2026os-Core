# 全量数据库部署指南

> 通过 123 云盘直链下载全量向量索引（79,192 条，从 312,632 条 Git Commit 中分层采样构建）。

---

## 一、你需要准备什么

| 要求 | 说明 |
|------|------|
| 磁盘空间 | ≥ 5 GB（压缩包 2.3 GB + 解压后 2.5 GB） |
| 网络 | 能访问 `1860205572.cdn.123clouddisk.com` |
| 时间 | 首次下载约 5-15 分钟（取决于网速） |
| 前置软件 | `curl`、`tar`、`gzip`（Linux 系统自带） |

## 二、部署（就两步）

### 第一步：进入项目根目录

```bash
cd CoreLinuxCommit
```

### 第二步：运行下载脚本

```bash
bash scripts/download_data_full.sh
```

脚本自动完成：

```
[1/3] 下载数据文件     → 约 2.3 GB，支持断点续传
[2/3] gzip 完整性校验  → 检查文件是否损坏
[3/3] 解压数据        → 释放到 data_full/ 目录
```

**如果下载中断了，直接重新运行就行**，会自动从断点继续：

```bash
bash scripts/download_data_full.sh
```

## 三、启动全量模式

```bash
export FAISS_INDEX_PATH=$(pwd)/data_full/faiss_index
source venv/bin/activate
python -m src.main
```

看到下面这行说明部署成功：

```
✓ 向量库就绪: 79,192 条
```

然后浏览器打开 `http://localhost:8000`。

## 四、验证

提交一个测试日志，看匹配补丁是否 > 0：

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "log_content": "BUG: unable to handle kernel NULL pointer dereference at 0000000000000028\nCall Trace:\n do_writepages+0x36/0x70\n ext4_writepages+0x1a2/0x3b0",
    "log_type": "dmesg",
    "top_k": 5,
    "enable_llm_explanation": false
  }'
```

或通过 API 查向量库大小：

```bash
curl http://localhost:8000/api/v1/stats | python3 -m json.tool | grep total_commits
# 输出: "total_commits": 79192
```

## 五、解压后的文件

```
data_full/
  ├── faiss_index.index      向量索引 (1.2 GB)
  ├── faiss_index.meta.json  元数据 (1.3 GB)
  └── index_progress.json    构建记录
```

## 六、常见问题

### 下载中断了？

重新运行脚本，`curl -C -` 会自动续传：

```bash
bash scripts/download_data_full.sh
```

### 磁盘空间不足？

```bash
df -h .                         # 检查可用空间
rm -rf data_full/               # 清理旧数据
bash scripts/download_data_full.sh
```

### 启动报"向量库为空"？

检查环境变量：

```bash
echo $FAISS_INDEX_PATH          # 应指向 data_full/faiss_index
ls $FAISS_INDEX_PATH.index      # 确认文件存在
```

### 想切回 Demo 模式（小数据）？

```bash
unset FAISS_INDEX_PATH
python -m src.main              # 自动使用 data/ 的 9,990 条数据
```

### 下载特别慢？

123 云盘 CDN 在国内速度正常。如果太慢，检查是否走了代理：

```bash
unset http_proxy https_proxy
bash scripts/download_data_full.sh
```

## 七、数据来源

| 项目 | 值 |
|------|-----|
| 数据来源 | [Linux Kernel Git](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git) |
| 已索引 Commit | 79,192（从 312,632 条全量采集中分层筛选） |
| 内核版本范围 | 4.9 ~ 6.13 |
| 向量模型 | BGE-M3 (1024维) |
| 索引类型 | FAISS IndexIVFFlat (IP度量) |
| 数据大小 | 压缩 2.3 GB / 解压 2.5 GB |
| 存储位置 | 123 云盘直链 CDN |
| 构建日期 | 2026-06-25 |

## 八、Demo vs 全量

| | Demo | 全量 |
|--|------|------|
| 数据目录 | `data/` | `data_full/` |
| 已索引 Commit | 9,990 | **79,192**（全量采集 312,632） |
| 大小 | ~80 MB | ~2.5 GB |
| 检索精度 | 基准 | **显著提升** |
| 适用场景 | 快速验证 | 正式演示/比赛 |
