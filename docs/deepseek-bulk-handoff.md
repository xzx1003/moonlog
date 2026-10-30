请验收 /Users/xzx/Documents/ChatGPT/moonlog 的按块摘要核心改造。先读 AGENTS.md、git diff，保留所有现有未提交改动；不 commit、不 push。

本轮核心：
- Sha256::feed_bytes(BytesView)：同步消费、不保留源视图，按 64 字节填充压缩块；feed_byte 保留，混用语义不变。
- nativeio.each_line 新增 observe_chunk；observe 改成默认 None 的可选字节回调，未指定时不再逐字节调用空闭包。指定时仍逐字节收到所有原始字节，但观察先于行消费，回调时序发生变化，需要明确审查。
- CLI scan_file、browser.Session.feed、compare 适配器改用块摘要。所有原始字节仍参与校验，逐行解码和上限保持原样。
- 新增独立 Python hashlib 期望值回归：0/1/55/56/63/64/65/127/128/129/65535/65536/65537 长度，多种块宽、空块、混用 feed_byte/feed_bytes、重复 hex。
- 81 单测、78 CLI、Node24 下13 Web已通过。Go对照1MiB档四场景完整输出一致。

请做：
1. 审查缓冲复用、视图生命周期、回调时序和错误退出行为，不准绕过 SHA-256 或减少扫描。新增 mbti API 是本轮预期变化，不要误判为只能新增私有 schedule。
2. 补必要的集成验收：跨64KiB读块的UTF-8、BOM/CRLF、末行无换行、超长行与非法UTF-8拒绝、多文件逐文件校验；优先复用现有测试，避免重复。
3. benchmarks/profile/bulk.py 可交错比较 /tmp/moonlog-before-bulk 与当前 _build/native/release/build/benchmarks/compare/compare.exe，默认100MiB档、预热1次、5轮。该 before 是已含 schedule 复用但尚未按块改造的二进制；不要与 /tmp/moonlog-profile-before 混淆。文件丢失时须独立重建对应版本，不能伪造。当前 bulk.json 只是10MiB档初测，不覆盖生产CLI上下文/报告。
4. 空闲时跑更大规模；记录负载、二进制哈希、输入哈希，逐次验证完整输出一致。观察read的变化是预期（去掉空回调），不能拿它当完全同码噪声对照。结果如实报告，勿声称全面超过Go。
5. 更新 benchmarks/profile 文档与 README 的优化入口，保留旧测量和历史边界。完整CLI与Go对照数据只有实际重跑才可更新，不能替换旧结果的二进制哈希。可在 /tmp 保存新结果。
6. DEVELOPER_DIR=/Library/Developer/CommandLineTools；Node24可用 /tmp/node24/bin/node。跑 moon info、moon fmt、make check/test/integration/web-test，确认所有接口变化有解释。

交付：修改清单、验证结果、前后数据及限制；不改前端，不提交、不推送。
