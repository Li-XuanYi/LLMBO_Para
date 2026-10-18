# 0.5C/1C 电热 ParEGO 与 LLMBO-MO 合成对照（2026-10-18）

代码基于35afd7ce4b8a9f96478bf58b829c6b783541cf64；主工程用户代码、旧实验和旧3C保持不动。实验驱动、配置、来源和包源码快照分别归档；这份文档不修改数值方法。

## 协议与边界

复用此前已知人工参数生成的真实DFN电压/电芯温度观测，R_fit=[0.5C,1C]、窗口0–60 s，初温300.15 K、环境298.15 K，显式人工电流2.5/5 A。人工边界不代表已确认的实测条件。每个参数点每倍率一次DFN+lumped求解同时产生U/T及热源，两个目标分别为选中倍率RMSE均值。
六参数electrothermal_4e2t及固定物性/活化能沿用synthetic_fixture_only来源。未使用实测XLSX或旧3C，不宣称实测参数辨识完成。
普通BO为无LLM的ParEGO；Full路线为LLM WarmStart+Region-Lift。两组各8初始化+20轮，共享参数范围、数据、ARD Matern GP/Gaussian EI、权重调度seed17、尺度[0.1 V,1 K]、增广系数0.05及HV参考点[10,10]（Y/scales空间）。
按固定均衡w=[0.5,0.5]标量化从各自完整历史选一个代表点；表内U/T属于同一参数。完整Pareto参数集另保留。初始化不同，因此属于端到端对照，不是Region-Lift单独消融。

## 实际完成状态与RMSE

| 方法 | BO轮数 | F_U (mV) | F_T (K) | HV | 本次新增DFN | 本段API | Region采纳 |
|---|---:|---:|---:|---:|---:|---:|---:|
| full_llmbo_mo | 20 | 3.935710833 | 0.029019274013 | 99.857638335823 | 56 | 21 | 0 |
| parego | 20 | 2.463683987 | 0.031633161991 | 99.593467653860 | 56 | 0 | 0 |

| 方法/倍率 | 电压RMSE (mV) | 电芯温度RMSE (K) |
|---|---:|---:|
| full_llmbo_mo/0.5C | 4.690360609 | 0.052883103892 |
| full_llmbo_mo/1C | 3.181061058 | 0.005155444134 |
| parego/0.5C | 2.179353142 | 0.038393027154 |
| parego/1C | 2.748014832 | 0.024873296828 |

Region与HTTP的实际分布（只统计各最终段，先前两次Warm超时成本另列）：

```json
{
  "full_llmbo_mo": {
    "round_outcomes": {
      "low_confidence": 1,
      "invalid_response": 19
    },
    "HTTP_attempts_in_arm": 21,
    "HTTP_200_in_arm": 2,
    "HTTP_error_types": {
      "TimeoutError": 15,
      "HTTPError": 1,
      "RemoteDisconnected": 1,
      "URLError": 2
    },
    "known_prompt_tokens": 8366,
    "known_completion_tokens": 1974,
    "requests_with_unknown_usage": 19
  },
  "parego": {
    "round_outcomes": {},
    "HTTP_attempts_in_arm": 0,
    "HTTP_200_in_arm": 0,
    "HTTP_error_types": {},
    "known_prompt_tokens": 0,
    "known_completion_tokens": 0,
    "requests_with_unknown_usage": 0
  }
}
```

**本次Region采纳0/20：实际选点等价于LLM WarmStart＋普通EI。不能把这次实验写成Region-Lift实际提升效果已验证。**

## 运行与成本证据

首次16候选请求和批准的8候选恢复均发生30s读超时，没有生成可用初始化点；两个失败档案和成本未删除。用户另行批准最后尝试：WarmStart8候选/120s、Region30s/次、新1800s墙钟，保留累计130solve并只增加API上限27→28，失败不再恢复。该上限是请求参数和总进程监督边界；超时不等同无供应商费用。
R2累计真实求解114/130，包含既有生成2次；本轮对照新增112次。API累计28/28，包含原401一次、替换端点核验4次、两次WarmStart超时及最终段请求。具体成功/失败请求和可获得的token usage见HTTP事件，不推断未知账单。
缩小输出的WarmStart请求为8候选，不能把本次初始化称为实际筛选了16个有效候选；初始化选择仍使用同一确定性Pareto+Max-Min规则。未新增核、目标、热参数或热模型。

## 验证层级

软件完整回归：314/314，失败0、错误0、跳过0，退出码0。证据D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\tests\native-bridge-final-full-1018094826952622。这次实验没有修改已测产品代码，新增驱动的软件模拟检查均单独归档，不冒充DFN结果或新增pytest数量。
真实DFN优化完成且深审计通过的组数：2/2；独立归档曲线RMSE复算两组完整通过：True。每组audit保留原生C/V、G/A、扩散率温度关系、冻结上下文/GP/EI、Region、Pareto/HV及实际成本回放。
基础R3的12-solve独立敏感性方案此前只完成1次生成，C/G分别扰动及完整R3验收未完成；本次R2优化不可替代该验收。实测辨识仍被电流轨迹、T测点与单位、初态、冷却条件及可靠数据来源阻塞。单个seed/短合成窗口不证明LLM增益、参数唯一可辨识或实测泛化。

## 档案

最终会话：D:\Users\aa133\Desktop\LLMBO_Para\runs\et-last\20261018T132825Z_c880efc1f9dc_160d6f95
逐候选和逐轮RMSE CSV、比较CSV、图PNG/PDF、complete Pareto参数、原始U/T曲线、全部HTTP诊断与审计JSON均随会话保存；各臂csv_directory记录原始普通BO与最后Full段的不同目录。
独立复算：D:\Users\aa133\Desktop\LLMBO_Para\runs\et-last\20261018T132825Z_c880efc1f9dc_160d6f95\independent-rmse-recheck.json
机器结果：D:\Users\aa133\Desktop\LLMBO_Para\runs\et-last\20261018T132825Z_c880efc1f9dc_160d6f95\combined-result.json
报告：D:\Users\aa133\Desktop\LLMBO_Para\runs\et-last\20261018T132825Z_c880efc1f9dc_160d6f95\comparison-report.md

后续最小实测验证：科研组确认0.5C/1C电流与时间、温度单位/测点、初始状态与冷却边界后另建research配置，先一个固定参数点双输出预检，再独立批准小预算辨识；保留2C后续验证，可靠3C另建配置和签名，继续保留旧流程。
