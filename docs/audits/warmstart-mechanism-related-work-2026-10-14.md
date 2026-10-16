# 当前WarmStart机制与相关工作对照

2026-10-14，北京时间。本轮仅阅读当前实现、Reference中的LLAMBO原实现和公开论文；没有修改算法、Prompt或启动实验。

## 当前实际流程

当前采用StagedQualityWarmInitializer，复用QualityWarmInitializer和原评价/缓存接口。它包含有真实仿真反馈的初始化搜索，已经比固定数量的零样本起点生成更重。

1. 输入LLM：任务及DFN固定工况、六参数名称/单位/范围、固定孔隙率、必要库存条件，以及已有真实反馈摘要。最近20条评价、整个历史中最接近完整覆盖的8点、至多8个最佳完整点提供不同的信息；不是把全部逐点曲线或全部历史原样发给LLM。没有专门微调模型。
2. 每次请求20个新候选。程序验证有限六维向量、参数边界和物理约束，去重；LLMClient还执行归一化距离的最小间距/保留数量检查。跨请求累积至少20个合法未评价候选，必要库存通过不等于DFN完整通过。
3. 另一次LLM请求从当前池选择4个已有索引送去真实仿真。该次选择只能选池内参数；后续生成请求仍可在原范围及必要物理约束交集内提出新点，没有永久固定的候选池，也没有用随机点替代。
4. 每个选中参数运行四倍率DFN。仅对覆盖完整实测时段的倍率计算RMSE，并计算末点/最后10%残差；提前截止保留时长及失败类别，四倍率完整目标为null。反馈写入后续请求，影响新生成与新选择。没有LLM伪造评分，也没有外推。
5. 不足2个完整点时，优先改善最差倍率覆盖率；达到2个后，恢复平均RMSE与适度多样性探索。切换时保存并清空旧优先级的未评价池，再生成新池。覆盖率是筛选依据，正式四倍率RMSE目标不变。
6. 满足最低评价数量且有至少8个完整点后，程序按四倍率平均RMSE取最多前16个，先保留最佳，再逐个选与已选点归一化最小距离最大的点，得到8起点。这一步是确定性的程序选择，不是LLM最后挑8点，也不等于直接取RMSE最低8点。
7. 8起点缓存复用，其他有效/部分有效筛选记录同样进入对应倍率GP，全部完成标签进入完成概率模型。之后由既有4GP和采集函数提出BO候选；本轮WarmStart不会持续接管BO迭代选点。

流程可表达为：任务与反馈 → LLM生成 → 程序合法性检查/积累候选池 → LLM选4 → 四倍率DFN → 实际误差/覆盖反馈；取得足够完整点后 → 程序选8 → GP与BO。

代码依据：`src/llmbo_para/quality_initialization.py`、`staged_initialization.py`、`llm.py`，以及`src/llmbo_para/prompts/warm_start_staged.txt`、`warm_start_select_staged.txt`。运行入口为`scripts/run_quality_warmstart_pilot.py --staged`。

## 与相关工作对照

**LLAMBO，ICLR 2024。** 其WarmStart部分用任务描述和不同丰富程度的数据卡进行零样本起点生成，再接GP/TPE。论文的WarmStart对照固定5个起点、10个随机种子，并比较随机、Sobol、LHS；报告LLM起点可有更强参数相关性和更低几何多样性。其整个框架另有利用评价历史的候选采样与代理模块，不能将整个LLAMBO都称为无反馈。当前实现沿用“任务语义→LLM起点”的思路，但额外加入候选池选择、可行性恢复、真实反馈循环及评价后筛选，不能称为原样复现论文WarmStart。

论文：[Large Language Models to Enhance Bayesian Optimization](https://arxiv.org/html/2402.03921v2)，重点第4节；[ICLR正式版本](https://proceedings.iclr.cc/paper_files/paper/2024/file/84b8d9fcb4e262fcd429544697e1e720-Paper-Conference.pdf)。作者[官方代码](https://github.com/tennisonliu/LLAMBO)，本地对应`Reference/LLAMBO-master/exp_warmstarting/init_warmstart.py`、`run_warmstart.py`及`templates/classification_fullcontext.txt`。

**BOLT，ICLR 2026。** 将历史任务BO得到的优质解用于微调LLM，面向新任务生成初始化候选，测试时保留单任务代理。它的优势来源包含跨任务经验积累。我们目前用通用模型和当前电池任务的上下文反馈，没有这类跨任务训练数据与微调过程，不能假设已具备相同知识迁移能力。

论文：[Scaling Multi-Task Bayesian Optimization with Large Language Models](https://proceedings.iclr.cc/paper_files/paper/2026/hash/a4a3689e5ca538e340f58cdd29f513a9-Abstract-Conference.html)。

## 对本项目的含义

当前机制已经能解决可行初始化，但“找到8点”与“只花8次仿真”不是一回事。最新运行实际保留80次失败筛选，再追加24次取得11完整点，选择8起点；最终GP使用104次筛选中的可用记录。论文与对照中必须将全部真实调用费用计入，不能只报告8起点＋5 BO。

现有多样性是候选几何间距，并未计算GP信息增益或六参数可辨识性。相关工作提示可以保留有物理依据的参数相关组合，不必要求各维独立或强制全域铺开；但本项目是否因此改善仍需对照验证。

当前WarmStart所选起点最佳59.834 mV，随后BO降到47.315 mV。这一轨迹支持“提供可行起点”，尚不支持“比随机起点更优”。应分别评估固定真实预算下的最佳RMSE、完整可行率和后续BO学习曲线；纯零样本起点、当前反馈筛选、随机/Sobol必须使用同样费用口径。

若下一轮要研究机制，最清楚的对照是分别评估一次语义起点生成和真实反馈恢复的增益，再控制几何多样性的强度；这是研究建议，本轮没有执行。

只读核查曾将历史提及的Multi_误当作根目录查找，目录不存在；随后使用已核实的Reference/LLAMBO-master/exp_warmstarting。没有影响代码或实验。OpenReview页面触发浏览器验证，改读ICLR会议正式PDF及arXiv正文，没有尝试绕过验证。
