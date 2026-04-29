<p align="center">
  <a href="http://tcci.ccf.org.cn/conference/2026/shared-tasks/"><img src="badge/NLPCC2026_BC.png" height="45"></a>
  <a href="https://sfl.hust.edu.cn/"><img src="badge/HUST.png" height="45"></a>
  <a href="https://fah.um.edu.mo/"><img src="badge/UM_FAH.png" height="45"></a>
</p>

[中文页](README_CN.md)

<!------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------->

# NLPCC2026-Task8: Factivity Inference Inconsistency Attack (FIIA)

## Updates

### 2026-04-27
1. The official dataset has been released in the `dataset` directory.
2. The [Available Tracks and Model Scope](#evaluation-operations-and-specifications) has been updated.
3. The [Attack Sample Validity Check](#attack-sample-validity-check) rules have been updated. The corresponding self-check script has been released in the `validate` directory.


## Q&A (Continuously Updated)

**Q1: Is the released dataset the official dataset to be used during the leaderboard competition stage, or is it only for practice?**  
A: The released dataset, which contains 1,089 data items, is the only official dataset for this task. It is not a practice set. No additional test set will be released during the leaderboard competition stage; only the evaluation system backend and leaderboard entry will be opened at that time. At the current stage, participating teams may already use the official dataset to select samples, adapt texts, conduct self-testing, and rank their candidate samples.

**Q2: Do I need to adapt all 1,089 data items?**  
A: No. Participating teams may freely select samples from the 1,089 official data items for adaptation and submit the samples that show better attack performance in self-testing. At most 200 samples will be counted toward the final score. If a submission file contains more than 200 samples, the system will only evaluate the first 200 samples in the submitted file. Therefore, teams are advised to complete sample filtering and ordering before submission.

**Q3: What role do the two large language models specified in this task play?**  
A: The two large language models specified in this task, Qwen and DeepSeek, serve as the “target models to be attacked.” Specifically, participating teams need to construct `text_attack` and call the specified model using the unified prompt provided in the task instructions, so that the model outputs a T/F/U answer for the given `hypothesis`. Each item should be queried 10 times, and the results of these 10 responses should be recorded. The greater the internal divergence among the 10 responses, the higher the score.

**Q4: Can I use large language models or other AI tools to help generate attack samples?**  
A: Yes. The organizing team does not impose restrictions on how attack texts are generated. Participating teams may generate candidate attack samples through manual rewriting, rule-based programs, large language model assistance, or other methods. The specified target models for this task may also be used for this purpose. However, the final submitted samples must still satisfy the format requirements and validity-checking rules specified in the task instructions.

**Q5: If I want to test the attack effect of my adapted texts on the specified large language models during the preparation stage, who is responsible for the resulting API costs?**  
A: API costs incurred during the preliminary exploration and testing stage shall be borne by the participating teams themselves. During the leaderboard competition stage (June 11–June 20), the evaluation system backend and leaderboard will be opened. At that time, teams may submit their attack datasets to the backend and obtain evaluation scores. The API costs incurred during this stage will be covered by the organizing team.

**Q6: What kind of adapted sentence counts as a successful attack?**

A: This task focuses on the **collapse of internal consistency** in large language models during factivity inference, rather than on whether the answer changes compared with the original sentence. Consider the following example:

Suppose we choose DeepSeek as the target model.

- DeepSeek’s 10 judgments on the original sentence A in the dataset are: `T/T/T/T/T/T/T/T/T/T`

Based on A, we create two adapted sentences, A1 and A2.

- DeepSeek’s 10 judgments on adapted sentence A1 are: `U/U/U/U/U/U/U/U/U/U`
- DeepSeek’s 10 judgments on adapted sentence A2 are: `T/U/T/U/T/U/T/U/T/U`

For sample A1, although the model’s judgment changes, the consistency rate is still 100%. The model remains logically self-consistent. Therefore, sentence A1 is an **invalid adapted sample**.

For sample A2, however, the consistency rate is only 50%. The model’s judgment is no longer stable, meaning that repeated queries may produce different answers. This indicates that the model has fallen into a logical inconsistency. Therefore, sentence A2 is a **highly successful attack sample**.


# Registration

Participants may register through either of the following channels:
1. Submit the online registration form via: https://alidocs.dingtalk.com/notable/share/form/v012M9qP5j5D8A1JO01_FSwM4Z8_xbMCeFp
2. Or complete the registration document (FIIA-Registration Form.docx) and submit it via email to liudh@hust.edu.cn.

# Task Introduction

Factivity Inference (FI) is a semantic understanding task related to judging the truthfulness of events, which primarily manifests as language users being able to infer the truthfulness of events based on the use of certain verbal linguistic components (e.g., “相信” (believe), “谎称” (falsely claim), “意识到” (realize)). For example:

* **Example 1-1:** 他们意识到局面已经不可挽回。（→局面已经不可挽回） (They realized that the situation was irreversible. → It is true that "the situation was irreversible".)
* **Example 1-2:** 他们没有意识到局面已经不可挽回。（→局面已经不可挽回） (They did not realize that the situation was irreversible. → It is true that "the situation was irreversible".)

From the two sentences in Example 1, we can infer the existence of a fact: “局面已经不可挽回” (the situation is irreversible). The ability to correctly acquire factual information from discourse and judge the speaker's subjective attitude towards factual information is extremely important for the application and interaction of current Large Language Models (LLMs) or agents. However, existing experiments show that the factivity inference results of large models are often affected by prompt induction, subtle text perturbations, or complex contexts, showing high instability. For example, in the following two sentences, based on the same questioning method and 10 rounds of calls to the same model, LLMs showed completely different self-consistency rates:

* **Example 2-1:** 人们都知道西部大开发需要资金和技术，但是负责人指出，从根本来看更需要知识和人才。→“西部大开发需要资金和技术”是否为真？ (Everyone knows that the Western Development requires capital and technology, but the person in charge pointed out that fundamentally, knowledge and talent are needed more. → Is "the Western Development requires capital and technology" true?) *(Inference Result: True=10/10, Self-consistency Rate=100%)* 
* **Example 2-2:** 人们不知道西部大开发需要资金和技术，因为负责人指出，从根本来看更需要知识和人才。→“西部大开发需要资金和技术”是否为真？ (People do not know that the Western Development requires capital and technology, because the person in charge pointed out that fundamentally, knowledge and talent are needed more. → Is "the Western Development requires capital and technology" true?) *(Inference Result: Uncertain=6/10, True=4/10, Self-consistency Rate=60%)* 

Comparative analysis of the two sentences in Example 2 reveals that only a minor perturbation of cognitive verbs and logical conjunctions (replacing “都知道” (know) with “不知道” (do not know), and “但是” (but) with “因为” (because)) may lead to a drastic decrease in the consistency of the large model's factual judgment regarding the target clause “西部大开发需要资金和技术” (the Western Development requires capital and technology). This instability may cause severe reliability issues in actual deployment, especially in high-stakes downstream applications such as judicial fact extraction and medical record mining.

Therefore, focusing on the consistency issue, this task adopts a Red Teaming attack mode for evaluation. Participating teams are required to creatively adapt the original corpus based on the Chinese factivity inference dataset provided by the organizers, under specified large models, prompts, and other environmental configurations. The goal is to mine as many text features as possible that cause a collapse in the large model's consistency during factivity inference, thereby providing a scientific basis for evaluating and improving the robustness of large models in complex language interaction scenarios.


# Dataset and Usage Instructions 

The corpus is primarily filtered from relevant Chinese corpora and has been manually annotated and proofread by the evaluation organizers. The evaluation set contains 1,089 data items, covering approximately 70 Chinese factive predicates. The dataset used for the evaluation is published in JSON format, serving as the basis for text adaptation by participating teams.

Data Example:

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

* **`id`**: Refers to the data number in the dataset released by the organizers.
* **`predicate`**: Refers to the factive predicate, which is the core linguistic component for factivity inference. Most predicates are verbs, while a few are adjectives. During attack testing, modifying the content of this field within the `text` is prohibited.
* **`text_original`**: Entailing sentence. This field provides the context required for inference, and the model needs to rely on the content of this field to judge the truth value of the `hypothesis` field.
* **`hypothesis`**: Entailed sentence. This field provides the discriminative sentence required for factivity inference, and the model needs to use the content of the "text" field to judge the truth value of this field. During attack testing, modifying the content of this field within the `text` is prohibited.
* **`option`**: The result returned by the model should be a single letter, and only one value is permitted:
  * If the `hypothesis` is judged to be true based on the `text`, output "T".
  * If the `hypothesis` is judged to be false based on the `text`, output "F".
  * If the truth or falsity of the `hypothesis` cannot be determined based on the `text`, output "U".
  * If the model refuses to answer, or if the returned text does not meet the above answer specifications, the output will be forcibly marked as "R". This is an invalid answer and is not included in the final consistency rate calculation. Teams should avoid this situation during adaptation and testing.


# Evaluation Operations and Specifications

## Attack Methods

Participating teams should modify the content of the `text_original` field to minimize the self-consistency rate of the large model's inference results as much as possible. When adapting `text_original`, the contents corresponding to the `predicate` and `hypothesis` fields must be kept intact and undamaged.

Modifications should focus on linguistic syntactic or semantic categories, rather than seeking system vulnerabilities outside the natural language framework (such as injecting gibberish or unnatural instructions). We encourage participating teams to design attack paths from the dimension of linguistic features. Suggested starting points for adaptation include, but are not limited to:

* **Syntactic Transformation**: Adding new linguistic components to the original sentence, or displacing, deleting, and replacing existing components.
* **Grammatical Category Alteration**: Changing the linguistic attributes of related words, such as tense, aspect, voice, finiteness, number, definiteness, person, and classifier.
* **Pragmatic and Logical Traps**: Introducing pragmatic devices such as evaluative adverbials, polyphonic markers, passivization markers, logical traps, or contextual pressure.

To ensure compliance, we will implement a "Sample Validity Admission" check during the final evaluation phase; non-compliant samples will be considered invalid and will not be scored.

## Evaluation Operations and Specifications

Participating teams are required to conduct independent Multi-turn Prompting to the models via API. They must ask the model to judge the truth value of the `hypothesis` field based on the value of the `text` field, record the model's return results (T/F/U), and self-check its self-consistency rate. The selection range of models, prompt templates, and other evaluation-related environmental parameters are uniformly specified by the task organizers.

### (1) Available Tracks and Model Scope

This evaluation sets up two parallel and independent tracks. Participating teams may choose either the Qwen or DeepSeek model series as the attack target. Both are representative foundation models among current Chinese large language models, which helps ensure the validity and frontier relevance of this evaluation. Meanwhile, their API costs are relatively manageable, and both provide open-weight versions, enabling participating teams to conduct testing and verification through official APIs, third-party platforms, or local deployment. The specific model versions designated for each track are as follows:

|  | Track A (Qwen) | Track B (DeepSeek) |
| :--- | :--- | :--- |
| Model Name | `qwen3-30b-a3b-instruct-2507` | `deepseek-v4-flash` |
| Release Date | 2025-07 | 2026-04 |
| Parameters | 30.5B total parameters, 3.3B activated parameters | 284B total parameters, 13B activated parameters |
| Invocation Mode | Non-thinking mode | Non-thinking mode (thinking disabled) |
| Official API Pricing | Approx. ¥0.74 / 1M input tokens, ¥2.95 / 1M output tokens | Cache-hit input: ¥0.02 / 1M tokens; cache-miss input: ¥1.00 / 1M tokens; output: ¥2.00 / 1M tokens |
| API Website | [Alibaba Cloud Model Studio / DashScope](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-dashscope) | [DeepSeek API Docs](https://api-docs.deepseek.com/) |

> Note: API prices may change depending on the official platform, deployment region, cache-hit status, or promotional activities. Actual costs should be based on the real-time prices listed on the respective official platforms. During the leaderboard competition stage, the evaluation system backend will call the models through the two official API websites listed above. Therefore, to ensure consistency of the testing environment, participating teams are recommended to use the same platforms for model invocation and testing.

### (2) Prompt Template & Parameter Configuration
```text
根据“文本”的内容，判断“假设”的真值情况：
文本：{text_original/text_attack}
假设：{hypothesis}
只允许答复T/F/U（对应真/假/无法确定），禁止回复其他解释性内容。
```

Participating teams should fill the relevant fields of each item into this template and call the large language model to obtain the output. Each item should be tested repeatedly for 10 rounds.

To restore the ecological validity of large models in practical applications, parameters such as Temperature are set to the official recommended or default values for each model series. Participating teams are not allowed to modify them.

## Submission Requirements
Participating teams must organize the adapted items to be submitted into a JSON format output file. Each data entry in the output file should contain four fields: id, text_attack, response_original, and response_attack. For example:

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

The `response_original` and `response_attack` fields should contain all answers obtained by the participating team from the 10 repeated calls for the corresponding item. These fields are required for reference. After the team submits the attack set, the system backend will call the model based on text_attack to obtain the real output for calculating the actual score.

Participating teams do not need to perform attack operations on all items in the test set. They only need to submit the items that have actually been adapted. The maximum number of items counted towards the score is 200. Therefore, each team should test, filter, and sort the adapted data themselves, and submit the top 200 items with the best self-tested attack effects.

For example, if a team actually adapted 326 items and submitted all 326 items to the system as an attack sample set, the system will only calculate the inconsistency rate score of the top 200 items in the set as the final result.

In addition, all resources used by the participating teams need to be detailed in the final submitted technical report. All code and results from the experiments must be properly saved for future reference.

## Attack Sample Validity Check

To prevent participating teams from inducing unstable model outputs through large-scale rewriting, deletion of core factive information, or disruption of basic syntactic structures, this evaluation implements a “validity check” for attack samples. All submitted adapted data must pass the evaluation system’s validity check before entering the scoring phase. The leaderboard system will calculate scores only for valid sample sets that pass the validity check.

The evaluation system will verify submitted samples according to the following rules. If a sample fails the check, the system will return the corresponding rule number (R1–R5) and the reason for invalidation.

### R1. Basic Fields and ID Validity

If a data item is missing any of the four required fields, or if its `id` is invalid or does not exist in the original dataset, the sample will be judged as invalid.

### R2. Predicate Integrity

The adapted sentence (`text_attack`) must contain the factive predicate (`predicate`) from the original sample. If the predicate is missing from the adapted sentence, the sample will be judged as invalid.

### R3. Hypothesis Integrity

The adapted sentence (`text_attack`) should sufficiently retain the core content of the original hypothesis to be judged (`hypothesis`). The system will calculate the Longest Common Subsequence Coverage (LCS Coverage) between the `hypothesis` and the adapted sentence.

If this score is lower than 0.7, the sample will be judged as invalid.

### R4. Text Retention

To ensure that attack samples mainly introduce limited perturbations based on the original context, rather than rewriting the original sentence on a large scale, the system will calculate the text retention score between the adapted sentence and the original sentence. We use a character-level edit distance algorithm (Levenshtein Ratio) to quantify the degree of text modification, including insertion, deletion, and substitution operations.

If this score is lower than 0.65, it indicates that the modification is too extensive, and the sample will be judged as invalid.

### R5. Fluency Preservation

The adapted sentence must remain basically natural and coherent in terms of linguistic intuition and grammar. The system will use an automatic fluency scoring method based on language model loss to evaluate the degree of fluency degradation of the adapted sentence relative to the original sentence. Specifically, the system uses the open-source Chinese MacBERT model [hfl/chinese-macbert-base](https://huggingface.co/hfl/chinese-macbert-base) to calculate the language model loss of the original background sentence and the adapted background sentence, respectively. If the loss of the adapted sentence increases significantly compared with that of the original sentence, it suggests that the adaptation may have introduced unnatural expressions, structural disruption, or abnormal characters. The system will calculate a fluency score according to the degree of loss degradation. The score ranges from [0, 1].

If this score is lower than 0.6, the sample will be judged as invalid.

### Script and Program for Self-Check

The algorithmic implementations of the above validity check rules have been released in the `validate` directory of this repository. During the later leaderboard competition stage, the validity determination program used by the evaluation system backend will remain fully consistent with the publicly released self-check program.

At present, the self-check script needs to be downloaded locally by participating teams and run through a Python interpreter. To lower the usage barrier, the organizers are developing a simple graphical user interface program to help participating teams validate their data more conveniently. The graphical program is expected to be released within one week, and the organizers will notify all participating teams by email at that time.

Participating teams are encouraged to use the self-check program during the data adaptation process to conduct basic format checks and validity checks on their samples, so as to minimize submission errors or invalid samples caused by validity issues.


## Evaluation Metric

This task uses the **Consistency Attack Score (AttackScore)** as the final ranking criterion. A higher AttackScore indicates a stronger attack effect. The maximum possible score is 120. The metric is calculated in the following three steps.

### Multi-turn Inconsistency Rate (MIR) for a Single Item

For each attack sample that passes the validity check, the evaluation backend will perform 10 model calls on both the original sentence (`text_original`) and the attack sentence (`text_attack`). For each item, its Multi-turn Inconsistency Rate (MIR) is defined as follows:

$$
MIR = 1 - \frac{\max(c_T, c_F, c_U)}{10}
$$

where $c_T$, $c_F$, and $c_U$ denote the number of times the model outputs `T`, `F`, and `U` respectively across the 10 calls. For example, suppose the 10 outputs for one item are `T,T,T,T,T,T,F,F,F,U`. The most frequent answer is `T`, which appears 6 times. Therefore, the MIR of this item is $MIR = 1 - \frac{6}{10} = 0.4$. The more dispersed the model's answers are across multiple calls, the higher the MIR. In this task, the theoretical range of MIR is: $MIR \in [0, 0.6]$.

### Attack Score for a Single Item ($Score_i$)

Based on MIR, the attack score of a single item is defined as the increase in the **attack sentence MIR ($MIR_{attack}$)** over the **original sentence MIR ($MIR_{orig}$)**:

$$
Score_i = \max(MIR_{attack} - MIR_{orig}, 0)
$$

This means that an item receives a positive score only when the attack sentence induces higher inconsistency than the original sentence. If the attack sentence does not increase the inconsistency of the model's responses, the score of this item is 0. The theoretical range of $Score_i$ is: $Score_i \in [0, 0.6]$.

### Overall Attack Score (AttackScore)

The final attack score is the sum of the attack scores of all valid samples. For each team in each track, at most the first 200 valid attack samples in the submitted file will be counted:

$$
AttackScore = \sum_i Score_i
$$

Since the maximum score for a single item is 0.6 and at most 200 valid attack samples are counted, the theoretical range of AttackScore is: $AttackScore \in [0, 120]$.

> Note: Each original sample `id` may correspond to only one submitted attack sample. If a team submits multiple attack samples for the same `id` in the same submission file, only the first occurrence will be retained for scoring, and the duplicate samples will not be counted in the final score.


# Tentative Schedule

Please refer to http://tcci.ccf.org.cn/conference/2026/ for the official conference timeline.


# Awards & Conference Support (Updating)

* **NLPCC & CCF-NLP Certification**: The top 1 participating team of each track will be certified by NLPCC and CCF-NLP.
* **Cash Prize**: Pending.


# Organizer & Contact

**Organizer**:
* **Xuri Tang** (Huazhong University of Science and Technology) xrtang@hust.edu.cn
* **Yulin Yuan** (University of Macau) yulinyuan@um.edu.mo
* **Bin Li** (Nanjing Normal University)

**Contact**:
* **Daohuan Liu** (Huazhong University of Science and Technology) liudh@hust.edu.cn
* **Guanliang Cong** (University of Macau) guanliang.cong@connect.um.edu.mo
* **Junchao Wu** (University of Macau)

**Team Members**:
* **Huazhong University of Science and Technology**: Jiaoyang Su, Yu'er Wang
* **University of Macau**: Liwei Zhou, Tianqi Xun, Yang Chen, Mai Xu, Zehua Li, Yueyao Wang, Changling Li

# References

If you're new to this field, we believe the following papers can help you quickly get familiar with it (continuously updated):

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
