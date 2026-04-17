# Git 常用操作卡

> 这份文件只放当前仓库最常用、最适合直接复制粘贴的命令。
>
> 如果想看远端关系和用途说明，先看：
> `远端说明.md`

---

## 一、查看当前状态

### 查看远端

```bash
git remote -v
```

### 查看本地分支和跟踪关系

```bash
git branch -vv
```

### 查看工作区状态

```bash
git status --short
```

---

## 二、同步官方源码

当前标准主线是：

- 本地 `main`
- 跟踪 `upstream/main`
- 要求始终与 `upstream/main` 保持一致

### 抓取并快进更新本地 `main`

```bash
git fetch upstream
git checkout main
git pull --ff-only
```

### 如果需要直接把 `main` 收敛到官方最新提交

```bash
git fetch upstream
git branch -f main upstream/main
```

---

## 三、切回 iOS 定制分支

当前定制分支是：

- `lanhu-mcp-ios`
- 默认不设置上游跟踪，避免误从 fork 分支直接 `pull`

### 切到定制分支

```bash
git checkout lanhu-mcp-ios
```

### 查看它当前跟踪谁

```bash
git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads/lanhu-mcp-ios
```

---

## 四、把主线更新带进定制分支

当你已经更新完 `main`，再把主线更新带进 `lanhu-mcp-ios`：

```bash
git checkout lanhu-mcp-ios
git merge main
```

如果你更偏好线性历史，也可以自己改成 rebase，但默认推荐先用 `merge`，更稳。

---

## 五、推送到 Gitee fork

当前 Gitee fork 远端是：

- `gitee-fork`

### 推送 `main`

```bash
git checkout main
git push gitee-fork main
```

### 推送当前 iOS 定制分支

```bash
git checkout lanhu-mcp-ios
git push gitee-fork lanhu-mcp-ios
```

### 推送所有本地分支

```bash
git push gitee-fork --all
```

---

## 六、推送到 GitHub fork

当前 GitHub fork 远端是：

- `github-fork`

### 推送 `main`

```bash
git checkout main
git push github-fork main
```

### 推送当前 iOS 定制分支

```bash
git checkout lanhu-mcp-ios
git push github-fork lanhu-mcp-ios
```

### 推送所有本地分支

```bash
git push github-fork --all
```

---

## 七、添加新提交的常用流程

### 1. 查看改动

```bash
git status --short
```

### 2. 暂存全部改动

```bash
git add -A
```

### 3. 提交

```bash
git commit
```

### 4. 推送当前分支到 Gitee

```bash
git push gitee-fork lanhu-mcp-ios
```

### 5. 如果 fork 上的同名分支已经分叉，但本地才是权威状态

```bash
git push gitee-fork lanhu-mcp-ios --force-with-lease
git push github-fork lanhu-mcp-ios --force-with-lease
```

---

## 八、当前远端速记

### 原始源码

```text
upstream -> https://github.com/dsphper/lanhu-mcp.git
```

### GitHub fork

```text
github-fork -> https://github.com/Link-Start/lanhu-mcp-dsphper.git
```

### Gitee fork

```text
gitee-fork -> https://gitee.com/Link413/lanhu-mcp-iOS.git
```

---

## 九、注意事项

1. 默认不要往 `upstream` 推自定义改动。
2. `main` 是官方镜像分支，自定义开发放在 `lanhu-mcp-ios`。
3. `lanhu-mcp-ios` 的官方同步方式是 `merge main`，不是直接 `pull` fork 分支。
4. 如果 fork 上的同名分支被别处改写过，使用 `--force-with-lease` 修正，不要裸 `--force`。
