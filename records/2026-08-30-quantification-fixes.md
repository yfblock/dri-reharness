# 2026-08-30 论文量化问题修复记录

对应审查文档：`research/paper/v2/quantification-review.md`

## 修复内容

### P0-1 QEMU 复现链（已修复）

**根因**：commit `a8abe7e`（08-10）删除全部规则式发射器转 LLM-only，论文声称的
"确定性发射器基线"失去载体；08-24 的 qemu.json false 实为 LangChain 桥接
基础设施失败（非语义回归），且 `generate_paper_results.py` 与新 schema 不兼容直接崩溃。

**修复**：
- 从 `8a96a8d` 恢复 ~5,305 行规则式发射器至 `src/generator/rules/`（common/harness/
  baremetal/rust_baremetal/linux 六模块），经 `REHARNESS_GENERATION=rules` 显式启用；
  默认路径仍是 LLM 桥，不影响并行中的 LangChain 工作
- 修复新旧 IR 偏差 6 处：
  1. `..subsystem_runner` 相对导入层级（rules 深一层）
  2. 新 IR StateWrite 字段携带完整源表达式（`priv->pdev`）→ `sanitize_state_member()`
     净化，嵌套表达式降级为显式 UNSUPPORTED 注释，结构体成员循环去重
  3. 发射器静态 `edu_fops` 与 RIS 值临时变量撞名 → 改名 `{cid}_misc_fops`
  4. callbacks.py `canonical_args` 局部变量遮蔽同名函数（8a96a8d 时已坏）
  5. callbacks.py 缺 `normalize_module_ops` 导入
  6. lowering 锚点标签加 `__attribute__((unused))`（内核 CONFIG_WERROR）
- registrar 身份穿透：cli gen 从 manifest 读 `runtime.qemu.registrar`，
  platform_driver `.name` 与探针函数名（源函数名 `ftgpio_gpio_probe`）与
  registrar 设备匹配，probe 得以绑定
- `instrument_mmio.py` 仅对函数体内含 MMIO 原语的函数注入 `[rhfn]`
  （纯 remove/释放函数不再产生空段）
- `run_qemu_experiments.sh`：固定 `REHARNESS_GENERATION=rules`；build/extract/
  trace_match 失败改为记录行后继续，保证 qemu.json 总被诚实重写；qemu.json
  写入 `value_oracle` 与四级覆盖字段
- `generate_paper_results.py`：兼容两种实验键名，缺失字段显式降级（不再 KeyError）

**复跑结果**（qemu.json，确定性基线）：
- edu：probe=true, trace_oracle=true, value_oracle=EDU_TRACE_OK
- ftgpio：probe=true, trace_oracle=true（TRACE_MATCH_OK），覆盖 7/7 调用、
  6/6 模块、13/13 操作、8/8 寄存器 —— 与论文声明一致
- 其余 6 个为用户并行开发的子系统实验（amba/i2c/mdio/network/spi/usb/virtio），
  如实记录，不影响论文声明

### P0-2 18 项清单落地（已修复）

- 新增 `qa/verification/dw_apb_ssi_checklist.py`：4 编译 + 2 片选 + 3 中断 +
  3 配置 + 6 数据流，逐后端判定并输出逐项证据
- 结果 `research/experiments/results/dw-apb-ssi-checklist.json`：**9/18**。
  未关闭失败（全部真实）：逐后端严格编译（harness/baremetal 触发
  -Wunused-but-set；Linux 触发 CONFIG_WERROR 且产物缺结构体成员；
  Rust 与缓存内三个 tock-registers 版本宏语法均不兼容）与 Rust 的
  5 项缓冲区数据流（`txw=0` 占位，无缓冲区解引用）
- 论文摘要与 §6.5 已改为如实描述（C 后端通过相关项；编译与 Rust 数据流项
  作为开放失败报告）

### P1/P2 论文文本修正（已修复并重编译 PDF，13 页）

- §6.4：dwc2 ops 改 4,250（新宏）；报 68 未解析与 93.0% 总解析率；多源耗时
- §6.3：子集选择标准、strict-ready 驱动点名（新宏）、表 1 caption 分母口径
- §6.5：QEMU "仅尝试 2 例"分母声明；确定性模式可复现说明；清单如实描述
- §7.3：耗时改实测 6.0–11.8s（中位 9.6s）+ 多源 28.5–176.5s；新增冻结
  zero-shot holdout 数据段（12/12 编译、strict 7/7/5、11/12 硬件交互）
- 中文译稿 `paper-zh.md` 已同步以上全部修改

## 未修（需作者决策或新实验）

- synthesis-eligible 5/19 死指标：补实验或删除
- 启发式分数（RIS/FuncSpec/DevSpec）扣分分解
- IR 合并碰撞计数、修复轮数、first-pass 率（EXPERIMENT_DEBT 范畴）
- zero-shot 是否升级为主评估章节

## 遗留提醒

- `run.sh test` 的 generalization guard 失败（dw_readl 等 private layouts）
  是**独立于本轮**的既有问题（示例特化与冻结策略冲突），仍未修
- 例行验证：`python3 qa/verification/dw_apb_ssi_checklist.py`、
  `./run.sh qemu-experiments`、`python3 tools/reporting/generate_paper_results.py`

## 附：配图学术化改版（同日）

- 7 张中文图（`research/paper/v2/figures-zh/`）与论文 4 张英文 TikZ
  （sections_3_5/sections_6_8）统一改为学术风格：
  白底细黑框、直角、衬线字体、细 stealth 箭头；柱状图改 L 形轴 +
  向内刻度 + 黑描边柱 + 带框图例，删除网格与彩色圆角填充
- 修复的具体缺陷：fig1 右半连线穿框（重排规整两行）；fig6 反馈回路
  穿过后端组框与文字（改走底部绕行）+「接受」节点脱节；fig7 值标签
  越轴与轴题重叠（标签内移、注记框下移）；fig5 三层框错位与文字溢出
  （calc + 固定 text width 左对齐堆叠）
- 论文重编译通过：13 页、0 未定义引用；23 个 Overfull 为既有正文
  溢出（改图前已存在），与图片无关
- 中文译稿 paper-zh.md 引用同名 PNG，自动生效

## 附 2：胶水代码占比量化与统计图（同日晚）

- 新增 `qa/verification/glue_ratio_survey.py`：对 19 基线驱动 in-process 提取，
  按"被 ≥1 个已发射 RIS 操作引用的非空源行 = 设备核心行；其余非空行 = 集成
  （胶水）行"分类（空行不计；行级归属为近似，已在 caption 声明）
- 结果：聚合设备核心 9.5% / 集成 90.5%（逐驱动 4.0%–20.7%），
  `research/experiments/results/glue-ratio.json`
- `generate_paper_results.py` 新增宏 \GlueCorePct/\GlueGluePct/\GlueCodeLines
  与整图宏 \GlueRatioChart（逐驱动横向堆叠条 + 合计行 + 图例）
- 论文：§2.2 与 §6.2 补引用句；§6.2 新增 Figure 3（fig:glue-ratio），
  后续图自动顺移（readiness→Fig4、multisource→Fig5）；PDF 重编译 14 页 0 错误
- 中文译稿：新增图 3（fig8-glue-ratio.png 中文版），原图 3/4 顺移为图 4/5，
  §2.2 与 §6.2 段落同步
- 修复：generator 图例两项重叠（缩短文字并错开 x）

## 附 3：胶水占比升级为四分类（同日）

- `glue_ratio_survey.py` 升级 schema 2：二分 → 四分
  （设备核心 / 框架入口函数体 / 胶水·辅助及其它函数体 / 文件级声明与注册样板）。
  函数边界由 libclang（parse_translation_unit）给出，回调角色由 callback_map 给出
- 聚合构成：9.5% / 32.6% / 25.7% / 32.2%
- \GlueRatioChart 升级为四段堆叠条；新增宏 \GlueEntryPct/\GlueHelperPct/\GlueFileScopePct
- 论文 §2.2/§6.2/caption 更新为四分口径；PDF 14 页 0 错误
- 中文 fig8 与 paper-zh.md 同步
