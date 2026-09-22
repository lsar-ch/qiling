---
name: obsidian-archive
description: Obsidian 归档：把网页或公众号文章抓取、提炼并按规范存入知识库，更新索引与反向链接。
triggers: ["归档", "存到 obsidian", "存到知识库", "整理这篇"]
tools: ["obsidian", "web_fetch"]
enabled: true
---
# Obsidian 归档流程

1. **抓取原文**：优先使用已验证可用的抓取通道；公众号等直连受限来源走带渲染的抓取，不用裸 curl。
2. **核验元数据**：标题、作者/公众号、发布时间、原文 URL，缺一标注"未提供"。
3. **提炼正文**：保留事实与结构，去除广告、引导关注、重复段落；不逐字堆全文。
4. **规范落盘**：按知识库既定目录与命名规则新建笔记，写入 frontmatter（title/date/source/url/tags/status）。
5. **建立关联**：在合适的索引/MOC 登记，补相关笔记的 wikilink；检查是否已有同主题笔记并互链。
6. **回报**：给出新笔记路径与关联到的笔记，不重复贴正文。

单一事实源只写一次；写入后不反复重读校验。
