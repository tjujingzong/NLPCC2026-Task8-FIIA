<p align="center">
  <a href="http://tcci.ccf.org.cn/conference/2026/shared-tasks/"><img src="badge/NLPCC2026_BC.png" height="45"></a>
  <a href="https://sfl.hust.edu.cn/"><img src="badge/HUST.png" height="45"></a>
  <a href="https://fah.um.edu.mo/"><img src="badge/UM_FAH.png" height="45"></a>
</p>

[English Page](README.md)

<!------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------->

# NLPCC2026-任务8: 叙实性推理一致性攻击评测 (FIIA)


# 报名

有意参赛的团队或个人可通过以下任一渠道进行报名：
1. 通过以下链接提交在线报名表： https://alidocs.dingtalk.com/notable/share/form/v012M9qP5j5D8A1JO01_FSwM4Z8_xbMCeFp
2. 或填写报名文档 (FIIA-Registration Form.docx) 并通过电子邮件发送至 liudh@hust.edu.cn。

# 任务介绍

叙实性推理（Factivity Inference）是一项与判断事件真实性相关的语义理解任务，主要表现为语言使用者能够基于某些动词性语言成分（例如“相信”、“谎称”、“意识到”）的使用，推断所描述事件的真实性。例如：

* **例 1-1:** 他们意识到局面已经不可挽回。（→局面已经不可挽回=True）
* **例 1-2:** 他们没有意识到局面已经不可挽回。（→局面已经不可挽回=True）

从例1的两个句子中，我们可以推断出一个事实的存在：“局面已经不可挽回”。正确从语篇中获取事实信息并判断说话者对事实信息的主观态度的能力，对于当前大型语言模型（LLMs）或智能体的应用与交互极其重要。然而，现有实验表明，大模型的叙实性推理结果经常受到提示词诱导、细微文本扰动或复杂上下文的影响，表现出高度的不稳定性。例如，在以下两个句子中，基于相同的提问方式并对同一模型进行10轮调用，LLMs表现出了截然不同的自一致率（Self-consistency Rate）：

* **例 2-1:** 人们都知道西部大开发需要资金和技术，但是负责人指出，从根本来看更需要知识和人才。→“西部大开发需要资金和技术”是否为真？  *(推理结果：True=10/10，自洽率=100%)* 
* **例 2-2:** 人们不知道西部大开发需要资金和技术，因为负责人指出，从根本来看更需要知识和人才。→“西部大开发需要资金和技术”是否为真？  *(推理结果：Uncertain=6/10，True=4/10，自洽率=60%)* 

对比例2的两个句子可以发现，仅仅对认知动词和逻辑连词进行微小扰动（将“都知道”替换为“不知道”，将“但是”替换为“因为”），就可能导致大模型对目标子句“西部大开发需要资金和技术”的事实判断一致性急剧下降。这种不稳定性在实际部署中可能引发严重的可靠性问题，尤其是在诸如司法事实抽取、医疗病历挖掘等容错成本较高的下游应用上。

因此，本任务聚焦一致性问题、采用红队攻击模式展开评测，参赛队伍需要在指定的大模型、提示词及其他环境配置下，基于组织者提供的中文叙实性推理数据集，对原始语料进行创造性改编。目标是尽可能多地挖掘出导致大模型在叙实性推理中一致性崩溃的文本特征，从而为评估和提升大模型在复杂语言交互场景中的鲁棒性提供科学依据。


# 数据集与使用说明

语料主要从相关中文语料库中筛选，并由评测组织者进行人工标注和校对。评测集预计包含1000条数据，覆盖约300个中文叙实性谓词。评测所用数据集以JSON格式发布，作为参赛队伍进行文本改编的基础。

测试集数据示例：

```json
[ {
  "id": "0001",
  "predicate": "知道",
  "text_original": "人们都知道西部大开发需要资金和技术，但是负责人指出，从根本来看更需要知识和人才。",
  "hypothesis": "西部大开发需要资金和技术。",
  "option": {
    "T": "真",
    "F": "假",
    "U": "不能确定",
    "R": "模型拒绝回答"
  }
} ]
```

* **`id`**：指主办方发布的数据集中的数据编号。
* **`predicate`**：指叙实性谓词，是进行叙实性推理的核心语言成分。大多数谓词为动词，少数为形容词。在攻击测试期间，禁止修改`text`中该字段的内容。
* **`text_original`**：主蕴含句。该字段提供了推理所需的上下文，模型需要依赖此字段的内容来判断`hypothesis`字段的真值。
* **`hypothesis`**：被蕴含句。该字段提供了叙实性推理所需的判别句，模型需要利用`text`字段的内容来判断此字段的真值。在攻击测试期间，禁止修改`text`中该字段的内容。
* **`option`**：模型返回的结果应为单个字母，且仅允许包含一个值：
  * 如果根据`text`判断`hypothesis`为真，则输出“T”。
  * 如果根据`text`判断`hypothesis`为假，则输出“F”。
  * 如果根据`text`无法确定`hypothesis`的真假，则输出“U”。
  * 如果模型拒绝回答，或者返回的文本不符合上述回答规范，输出将被强制标记为“R”。这属于无效回答，不计入最终的自一致率计算。参赛队伍在改编和测试期间应尽量避免出现此情况。


# 攻击评测规则

## 攻击方法

参赛队伍必须修改`text_original`字段的内容，以尽可能降低大模型推理结果的自洽率。在改编`text_original`时，必须保持`predicate`和`hypothesis`字段对应的内容完整无损。

修改应侧重于语言的句法或语义范畴，而不是在自然语言框架之外寻找系统漏洞（例如注入乱码或不自然的指令）。我们鼓励参赛队伍从语言特征的维度设计攻击路径。建议的改编切入点包括但不限于：

* **句法转换**：在原句中添加新的语言成分，或对现有成分进行移位、删除和替换。
* **语法范畴变更**：改变相关词语的语言属性，如时态、体、语态、限定性、数、定指、人称和量词。
* **语用与逻辑陷阱**：引入评注性状语、复调标记、被动标记、逻辑陷阱或语境压力等语用手段。

为了确保合规性，我们将在最终评估阶段执行“样本有效性准入”检查；不合规的样本将被视为无效且不予计分。

## 评测操作与规范

参赛队伍需要通过API对模型进行独立的多轮提示（Multi-turn Prompting）。要求模型基于`text`字段的值来判断`hypothesis`字段的真值，记录模型返回的结果（T/F/U），并自查其自洽率。模型的选择范围、提示模板以及其他与评测相关的环境参数变量由组织方统一指定。

### (1) 可选模型范围（暂定）

为了全面、公平地评估攻击策略的有效性，本评测设立了两个平行的独立赛道。每个赛道受测模型的具体版本由组织者唯一指定：

| 模型系列 | 赛道名称 | 具体模型 (API节点) |
| :--- | :--- | :--- |
| Qwen | 赛道 A | Qwen2.5-72B-Instruct |
| DeepSeek | 赛道 B | DeepSeek-V3 |

选择 Qwen 和 DeepSeek 系列作为测试基线主要基于以下三点考虑：
1.  它们是目前公认代表中文LLMs最高水平的基础模型，确保了本次评测的有效性和前沿性。
2.  它们代表了当前大模型演进中两种主流且不同的技术路线，具有较强的样本代表性。
3.  它们均提供开源权重版本，具备对学术界友好的开源生态和白盒复现潜力。

### (2) 提示词与参数配置（暂定）

```text
根据“文本”的内容，判断“假设”的真值情况：
文本：{text}
假设：{hypothesis}
只允许答复T/F/U（对应真/假/无法确定），禁止回复其他解释性内容。
```

为了还原大模型在实际应用中的生态效度，Temperature等参数均设置为各模型系列官方推荐或默认的值。参赛队伍不得对其进行修改。

## 提交要求
参赛队伍需要将待提交的改编数据整理为 JSON 格式的输出文件。输出文件中的每条数据应包含四个字段：`id`、`text_attack`、`response_original` 和 `response_attack`。例如：

```json
[
  {
    "id": "0001",
    "text_attack": "人们不知道西部大开发需要资金和技术，因为负责人指出，从根本来看更需要知识和人才。",
    "response_original": "T/T/T/T/T/T/T/T/T/T",
    "response_attack": " U/U/U/T/U/T/T/U/U/T"
  }
]
```

`response_original`和`response_attack`字段仅供参考。队伍提交攻击集后，系统后台将基于`text_attack`调用模型以获取真实输出，从而计算实际得分。

参赛队伍无需对测试集中的全部数据进行攻击操作。只需提交实际已改编的数据。计入总分的最多数据条数为 200 条。因此，各队伍应自行对改编数据进行测试、筛选和排序，并提交自测攻击效果最好的前 200 条数据。

例如，如果某支队伍实际改编了 326 条数据，并将这 326 条数据作为攻击样本集全部提交给系统，系统将仅计算该数据集中前 200 条数据的不一致率得分作为最终成绩。

此外，参赛队伍使用的所有资源均需在最终提交的技术报告中予以详细说明。实验的所有代码和结果必须妥善保存，以备日后查阅。

## 攻击样本的有效性检查

为禁止通过大规模重写、删除核心叙实性信息、破坏基本句法结构等方式诱导模型输出不稳定结果，本评测对攻击样本实行“有效性检查”。所有提交的改编数据在进入评分阶段前，必须通过评测系统的“有效性检查”。排行榜系统最终只会对通过“有效性检查”的有效样本集进行计分。

评测系统将按照以下规则对提交样本进行核验。若样本未通过检查，系统将返回相应的规则编号（R1–R5）及无效原因。

### R1.基础字段与 ID 合法性

若数据项缺少必要的4个字段，或 id 非法/不存在，该样本将被判定为无效。

### R2.谓词完整性

改编句（`text_attack`）中必须包含原始样本的叙实性谓词（`predicate`）。如果改编句中缺失该谓词，或提交数据中的谓词字段与原始数据不一致，该样本将被判定为无效。

### R3.小句完整性

改编句（`text_attack`）应充分保留原始待判断小句（`hypothesis`）的核心内容。系统将计算其与改编句之间的最长公共子序列覆盖率（LCS Coverage）。

此项分数若低于 0.7，该样本将被判定为无效。

### R4.文本保留度

为确保攻击样本主要在原始上下文基础上进行有限扰动，而非对原句进行大规模重写，系统将计算改编句与原句之间的文本保留度。我们使用字符级别的编辑距离算法（Levenshtein Ratio）来量化文本修改的程度（包括增、删、改操作）。

此项分数若低于 0.65，则说明修改幅度过大，该样本将被判定为无效。

### R5.通顺保持度

改编后的句子在语感和语法上必须保持基本自然、连贯。系统将采用基于语言模型损失的自动流畅度评分方法，对改编句相对于原句的流畅度劣化程度进行评估。系统采用开源的中文 MacBERT 模型 [hfl/chinese-macbert-base](https://huggingface.co/hfl/chinese-macbert-base)，分别计算原始背景句和改编后背景句的语言模型损失值（loss）。若改编句的损失值相对于原句显著升高，则说明该改编可能引入了不自然表达、结构破坏或异常字符。系统将根据损失劣化程度计算流畅度分数，评分区间为 [0, 1]。

此项分数若低于 0.6，该样本将被判定为无效。

### 自查脚本与程序

上述有效性检查规则所涉及的算法实现（包括 Python 检测脚本及配套语言模型）均已公布于本仓库的 validate 目录中。建议参赛队伍在数据改编过程中及时使用自查脚本（validate.py）对样本进行基础格式检查与有效性核查，以尽可能避免最终提交时因样本有效性问题导致提交异常或样本无效。

在后期冲榜阶段，评测系统后台使用的有效性判定程序将与公开发布的自查程序保持完全一致。

当前自查脚本需由参赛队伍下载至本地，并通过 Python 解释器运行。为降低使用门槛，组织方正在开发配套的简易图形界面程序，以便参赛队伍更加便捷地完成数据校验。图形化程序预计将于一周内发布，届时组织方将通过邮件通知各参赛队伍。

如对“有效性检测”环节有任何疑问，欢迎各参赛队伍通过邮件联系组织方咨询。


# 评价标准（待更新）

Since the evaluation mode is a red teaming attack, this task evaluates performance by measuring the "attack success rate" (Weighted-MIS). The overall calculation process is divided into the following two steps.

## Multi-turn Inconsistency Score (MIS)

This metric is the basic scoring module, used to calculate the degree of answer dispersion for a single item and a specific set. The calculation formula is:

$$MIS=\frac{1}{N}\sum_{i=1}^{N}(1-\frac{\max(c_i)}{k_i})$$ 

Where $N$ is the total number of valid attack items submitted by the participating team, $k_i$ is the total number of questioning (or attack) rounds initiated for the $i$-th item (usually a fixed value $K$, such as 10 rounds), and $\max(c_i)$ is the count of the most frequent answer (T/F/U) among the $k_i$ rounds of replies for the $i$-th item.

Assuming a total of 10 calls are made for a certain item, and the model's reply distribution is 6 T's, 3 F's, and 1 U. Then the count of the highest frequency answer $\max(c_i) = 6$, so the self-consistency rate of the item is 0.6, and its inconsistency rate is 0.4. A higher MIS score indicates that the submitted attack samples trigger a higher inconsistency rate, meaning the attack is more successful.

## Multi-class Weighted Score (Weighted-MIS)

Factivity inference capabilities show significant differences across different types of verbs (such as cognitive verbs, speech verbs, evaluative verbs, etc.). To prevent participating teams from stacking data and overfitting scores on a few highly vulnerable words (such as "抱怨" / complain), we further introduce a weighting mechanism based on the classification of factive verbs. This rewards participating teams for designing attack strategies that cover as many verb types as possible and possess broad linguistic generalization capabilities.

The evaluation backend will calculate the MIS score for each category separately based on the verb classification table provided by the organizers, and then perform an equal-weight macro-average summation across all categories:

$$Weighted\_MIS=\frac{1}{F}\sum_{j=1}^{F}MIS_j$$

Where $F$ is the number of verb categories, and $MIS_j$ is the score of valid submitted samples under the $j$-th category of words. The final ranking basis is the Weighted-MIS.


# 暂定日程

请参阅 http://tcci.ccf.org.cn/conference/2026/ 获取官方会议时间表。


# 奖项与会议支持（更新中）

* **NLPCC 与 CCF-NLP 证书**：每个赛道排名第一的参赛队伍将获得 NLPCC 和 CCF-NLP 的获奖证书。
* **奖金支持**：正在争取中。


# 组织方团队

**任务组织者**：
* **唐旭日**（华中科技大学教授）xrtang@hust.edu.cn
* **袁毓林**（澳门大学教授）yulinyuan@um.edu.mo
* **李斌**（南京师范大学教授）

**任务联系人**：
* **刘道焕**（华中科技大学）liudh@hust.edu.cn
* **丛冠良**（澳门大学）guanliang.cong@connect.um.edu.mo
* **吴俊潮**（澳门大学）

**团队成员**：
* **华中科技大学**：苏佼阳, 王宇儿
* **澳门大学**：周立炜, 寻天琦, 陈阳, 徐劢, 李泽华, 王月瑶, 李昌玲


# 参考文献

如果您是该领域的新手，以下论文将能帮助您快速熟悉相关内容（持续更新中）：

[1]陈振宇 & 姜毅宁.(2018).事实性与叙实性——通向直陈世界的晦暗与透明. 语言研究集刊(01),15-37+372-373. doi:CNKI:SUN:YJJK.0.2018-01-002.

[2]袁毓林.(2014).隐性否定动词的叙实性和极项允准功能. 语言科学(06),575-586. doi:CNKI:SUN:YYKE.0.2014-06-002.

[3]袁毓林.(2020).“忘记”类动词的叙实性漂移及其概念结构基础. 中国语文(05),515-526+638. doi:CNKI:SUN:YWZG.0.2020-05-001.

[4]袁毓林.(2020).叙实性和事实性：语言推理的两种导航机制. 语文研究(01),1-9. doi:CNKI:SUN:YWYJ.0.2020-01-001.

[5]袁毓林.(2020).“记得”的叙实性漂移及其概念结构基础. 语言教学与研究(01),36-47. doi:CNKI:SUN:YYJX.0.2020-01-007.

[6]袁毓林.(2021).从语言的“多声性”看“假装”句的解读歧异. 语言战略研究(05),77-90. doi:10.19689/j.cnki.cn10-1361/h.20210506.

[7]张帆.(2024).“假装”类动词宾语的类型及其真值判定理据. 中国语言学报(00),157-170. doi:CNKI:SUN:XBYT.0.2024-00-012.

[8]李新良.(2018).“感觉”类动词的叙实性及其漂移问题研究. 语言教学与研究(05),65-75. doi:CNKI:SUN:YYJX.0.2018-05-007.

[9]李新良.(2020). 现代汉语动词的叙实性研究. 北京: 北京大学出版社.

[10]李新良 & 袁毓林.(2016).反叙实动词宾语真假的语法条件及其概念动因. 当代语言学(02),194-215. doi:CNKI:SUN:DDYX.0.2016-02-004.

[11]李新良 & 袁毓林.(2017).“知道”的叙实性及其置信度变异的语法环境. 中国语文(01),42-52+127. doi:CNKI:SUN:YWZG.0.2017-01-003.

[12]李新良、袁毓林等.(2023). 叙实性与事实性理论及其运用. 北京: 外语教学与研究出版社.

[13]Kiparsky & Kiparsky. (1970). Fact. In M. Bierwisch & K. Heidolph (eds.). Progress in Linguistics. The Hague: Mouton. 143-147.

[14]袁毓林 (2023).“X不敢相信Y”构式的叙实性逆转功能与魔术效应——表示‘当事实颠覆信念之后不情愿地悬置不信任’的心理经验. 中国语文(04),387-399+510.
