/*
 * 速豹七大质量智能体工作空间与子智能体配置
 * 来源：《七个质量智能体.docx》
 *
 * 注意：飞书接入本阶段仅用于界面能力展示，不调用飞书接口。
 */
(function () {
    'use strict';

    const CAP = {
        DOC: '文档：文档生成与解析',
        DATA: '数据：数据分析与可视化',
        KB: '知识库：知识沉淀与问答',
        SEARCH: '检索：联网检索',
        DASHBOARD: '看板：网页看板生成',
        EMAIL: '邮件：邮件收发',
        AUTOMATION: '自动化：定时任务与提醒',
        FEISHU: '协同：飞书（规划中）'
    };

    function buildSubagents(workspaceId, rows) {
        return rows.map(function (row, index) {
            return {
                id: workspaceId + '-sub-' + String(index + 1).padStart(2, '0'),
                name: row[0],
                desc: row[1],
                capabilities: row[2]
            };
        });
    }

    const workspaces = {
        'project-development-quality-agent': {
            name: '项目开发质量智能体',
            icon: '🚘',
            color: '#2f6be6',
            slogan: '前置拦截，缩短周期',
            desc: '贯穿研发项目管理的各个阶段，提高研发效率，智能管控研发全流程质量。',
            subagents: buildSubagents('project-development-quality-agent', [
                ['APQP 文件助手', '按 APQP 五阶段生成或核对交付物清单，并跟踪交付状态。', [CAP.DOC, CAP.FEISHU]],
                ['特殊特性管理助手', '汇总 SC/CC 特殊特性清单，输出特性矩阵及向制造端传递的清单。', [CAP.DOC, CAP.DATA]],
                ['DVP&R 设计验证助手', '生成 DVP 计划模板，汇总各项试验结果并输出设计验证报告。', [CAP.DOC, CAP.DATA]],
                ['设计评审助手', '生成评审检查单与纪要模板，形成评审问题清单并跟踪闭环。', [CAP.DOC, CAP.FEISHU]],
                ['阀点评审材料助手', '按开发节点（G8～G1 等）汇总交付物齐套性，生成评审汇报材料。', [CAP.DOC]],
                ['法规标准检索助手', '检索 GB、GB/T、ECE 及行业法规标准，输出解读摘要与符合性提示。', [CAP.SEARCH, CAP.DOC]],
                ['设计变更管理助手', '生成和解析 ECR/ECN 文档，形成影响件核对清单与变更通知。', [CAP.DOC, CAP.EMAIL, CAP.FEISHU]],
                ['研发问题跟踪助手', '管理试制与试验问题台账，对到期未关闭事项进行提醒。', [CAP.FEISHU, CAP.AUTOMATION]],
                ['电驱桥验证分析助手', '导入电驱桥台架试验数据，整理趋势图并生成试验报告。', [CAP.DATA, CAP.DOC]],
                ['可靠性分析助手', '基于试验或售后数据，对失效率和寿命分布进行初步统计分析。', [CAP.DATA]],
                ['经验教训库助手', '将已闭环问题结构化沉淀为 Lessons Learned，支持检索与复用。', [CAP.KB]]
            ])
        },
        'process-quality-control-agent': {
            name: '过程质量管控智能体',
            icon: '⚙️',
            color: '#168b83',
            slogan: '稳质降废，提效减损',
            desc: '快速分析处理过程中的质量问题，判定波动并协助进行闭环处置。',
            subagents: buildSubagents('process-quality-control-agent', [
                ['数据分析与可视化助手', '导入检验记录，统计直通率、不良率和缺陷分布。', [CAP.DATA]],
                ['SPC 离线分析助手', '基于导出数据绘制控制图，计算 Cp、Cpk、Ppk 并进行判异。', [CAP.DATA, CAP.DASHBOARD]],
                ['不合格品管理助手', '生成 NCR 报告、维护台账并跟踪处置闭环。', [CAP.DOC, CAP.FEISHU]],
                ['首件检验助手', '生成首件记录模板，汇总检验结果并标记异常。', [CAP.DOC, CAP.DATA]],
                ['点检巡检计划助手', '生成点检与巡检计划，并展示日程、待办和执行提醒能力。', [CAP.FEISHU, CAP.AUTOMATION]],
                ['分层审核（LPA）助手', '生成各层级审核检查表，汇总不符合项并跟踪整改。', [CAP.DOC, CAP.FEISHU]],
                ['质量报表机器人', '按周期生成质量日报、周报和月报，并展示推送能力。', [CAP.AUTOMATION, CAP.EMAIL, CAP.FEISHU]],
                ['防错验证清单助手', '管理防错装置清单与验证记录，并展示到期提醒能力。', [CAP.FEISHU, CAP.AUTOMATION]],
                ['质量看板生成助手', '生成可视化质量网页看板，供车间或办公室展示。', [CAP.DASHBOARD]]
            ])
        },
        'supplier-quality-agent': {
            name: '供应商质量智能体',
            icon: '🔗',
            color: '#b4771f',
            slogan: '严控源头，减少问题',
            desc: '全周期管控供应商质量，智能评级预警，协同处置来料异常风险。',
            subagents: buildSubagents('supplier-quality-agent', [
                ['准入评审助手', '核对供应商准入资料清单，生成评审表与评审报告。', [CAP.DOC]],
                ['质量协议助手', '生成供应商质量协议或质量目标协议模板，并支持版本管理。', [CAP.DOC]],
                ['供应商审核助手', '编制年度审核计划、过程审核检查表和审核报告。', [CAP.DOC, CAP.AUTOMATION]],
                ['PPAP 审查助手', '按 PPAP 18 项资料核对齐套性，输出审查结论清单。', [CAP.DOC, CAP.KB]],
                ['来料分析可视化助手', '分析来料检验批合格率、PPM 和缺陷分布。', [CAP.DATA]],
                ['绩效评价及分析助手', '按月或季度生成供应商质量情况、评价结果与排名。', [CAP.DATA, CAP.DOC]],
                ['供应商跟踪助手', '维护供应商整改台账和效果验证记录，展示超期提醒能力。', [CAP.FEISHU, CAP.AUTOMATION]],
                ['来料异常通报助手', '生成 SCAR 或异常通知单，支持邮件发送并记录台账。', [CAP.EMAIL, CAP.DOC]],
                ['分级管理助手', '依据绩效数据输出 A/B/C 分级建议及差异化管控措施。', [CAP.DATA]],
                ['定点评估助手', '生成新零件或新供应商质量风险评估表与风险清单。', [CAP.DOC]],
                ['供应商月报助手', '汇总供应商质量表现，按周期生成月度报告。', [CAP.AUTOMATION, CAP.DOC]]
            ])
        },
        'aftersales-quality-agent': {
            name: '售后质量智能体',
            icon: '🛡️',
            color: '#d14a52',
            slogan: '降低索赔，提升口碑',
            desc: '根据售后质量信息进行分析，得出故障模式、趋势统计等结论。',
            subagents: buildSubagents('aftersales-quality-agent', [
                ['售后分析与可视化助手', '导入维修或索赔数据，进行 Pareto、趋势和区域分布分析。', [CAP.DATA]],
                ['故障模式统计助手', '维护故障模式库，输出售后 TOP 问题清单。', [CAP.DATA, CAP.KB]],
                ['售后质量月报机器人', '按周期生成售后质量月报或快报，并展示推送能力。', [CAP.AUTOMATION, CAP.EMAIL, CAP.FEISHU]],
                ['客户投诉管理助手', '管理投诉台账、生成回复函并展示闭环到期提醒能力。', [CAP.DOC, CAP.FEISHU]],
                ['三包索赔分析助手', '统计索赔金额和索赔率，识别异常车型与异常部件。', [CAP.DATA]],
                ['市场信息收集助手', '汇总系统、服务网点和驻外人员的质量反馈。', [CAP.FEISHU]],
                ['召回/服务行动助手', '生成活动通知模板，整理涉及车辆清单并维护完成进度台账。', [CAP.DOC, CAP.FEISHU]],
                ['满意度调查助手', '设计调查问卷，分析回收数据并生成统计分析报告。', [CAP.DATA, CAP.DOC]],
                ['电驱桥售后分析助手', '汇总电驱桥失效件信息，分析失效模式分布与批次。', [CAP.DATA]],
                ['千车故障率核算助手', '基于销量和故障数据核算 IPTV、CPV 等核心指标。', [CAP.DATA]]
            ])
        },
        'quality-system-agent': {
            name: '体系智能体',
            icon: '📚',
            color: '#7856d8',
            slogan: '合规提效，体系落地',
            desc: '智能管理体系文件，监控合规运行，支撑内审外审持续优化。',
            subagents: buildSubagents('quality-system-agent', [
                ['体系文件管理助手', '起草和修订程序文件或制度，维护受控文件清单。', [CAP.DOC, CAP.FEISHU]],
                ['内审助手', '编制审核计划、生成条款检查表并输出不符合报告。', [CAP.DOC, CAP.AUTOMATION]],
                ['管理评审助手', '汇总管理评审输入资料，并跟踪决议事项闭环。', [CAP.DOC, CAP.FEISHU]],
                ['标准条款问答助手', '提供 IATF 16949、ISO 9001 条款解读与实施问答。', [CAP.KB]],
                ['法规标准监测助手', '定期联网检索标准法规更新，输出差异提示。', [CAP.AUTOMATION, CAP.SEARCH]],
                ['质量目标看板助手', '汇总质量 KPI 数据，生成目标达成看板和月报。', [CAP.DATA, CAP.DASHBOARD]],
                ['质量培训助手', '生成培训教材与考试题，管理培训记录台账。', [CAP.DOC, CAP.FEISHU]],
                ['制度问答机器人', '基于公司体系文件知识库提供随问随答服务。', [CAP.KB]],
                ['文件复审提醒助手', '管理文件有效期，展示到期复审提醒能力。', [CAP.AUTOMATION]],
                ['文件修订比对助手', '比对新旧文件版本差异，自动生成修订说明。', [CAP.DOC]]
            ])
        },
        'measurement-laboratory-agent': {
            name: '测量与实验室智能体',
            icon: '🔬',
            color: '#2387b8',
            slogan: '精准测量，高效可靠',
            desc: '管控测量与实验全流程，校核数据，保障检测结果精准可信。',
            subagents: buildSubagents('measurement-laboratory-agent', [
                ['MSA 分析助手', '导入测量数据，计算 GR&R、偏倚、线性和稳定性并生成报告。', [CAP.DATA]],
                ['计量器具台账助手', '维护计量器具台账，查询使用状态与检定周期。', [CAP.FEISHU]],
                ['校准提醒助手', '展示校准或检定到期时对责任人与实验室的提醒能力。', [CAP.AUTOMATION, CAP.FEISHU]],
                ['检测报告生成助手', '按模板批量生成尺寸、性能和材料检测报告。', [CAP.DOC]],
                ['实验数据分析助手', '完成试验数据清洗、统计、绘图与结论摘要。', [CAP.DATA]],
                ['作业指导书助手', '编制实验室作业指导书并支持版本管理。', [CAP.DOC]],
                ['不确定度评定助手', '提供测量不确定度计算模板并生成评定报告。', [CAP.DATA, CAP.DOC]],
                ['实验室审核助手', '生成 ISO/IEC 17025 检查表并跟踪内审不符合项整改。', [CAP.DOC, CAP.FEISHU]],
                ['样品管理助手', '管理样品或样件收发存台账，并展示留样到期提醒能力。', [CAP.FEISHU, CAP.AUTOMATION]],
                ['台架试验报告助手', '汇总电驱桥台架试验数据、绘制曲线并生成报告。', [CAP.DATA, CAP.DOC]]
            ])
        },
        'continuous-improvement-agent': {
            name: '持续改进智能体',
            icon: '📈',
            color: '#1a9b62',
            slogan: '质效跃升，持续精进（可试用）',
            desc: '挖掘质量痛点，驱动改进项目实施，追踪进度并实现闭环。',
            subagents: buildSubagents('continuous-improvement-agent', [
                ['问题聚合及改进机会助手', '汇聚售后、制造和供应商不良信息，分析各业务模块质量数据，识别 TOP 损失与改进方向。', [CAP.DATA]],
                ['年度改进规划助手', '生成年度质量改进规划文档与目标分解表。', [CAP.DOC]],
                ['改善提案管理助手', '管理提案台账、评审记录、成果统计和奖励名单。', [CAP.FEISHU, CAP.DOC]],
                ['QC小组活动助手', '管理课题登记与活动记录，生成成果报告或发布 PPT。', [CAP.DOC]],
                ['六西格玛项目助手', '支持 DMAIC 各阶段文档和假设检验、回归、方差分析。', [CAP.DOC, CAP.DATA]],
                ['改进项目看板助手', '基于知识库查询项目阶段状态，汇总延迟风险并输出项目台账、进度提醒和月度进展报告。', [CAP.FEISHU, CAP.AUTOMATION]],
                ['质量成本分析助手', '分析预防、鉴定及内外部损失成本，输出质量成本报告和优化建议。', [CAP.DATA]],
                ['改进效果验证助手', '分析改善前后数据并进行统计检验解读，输出效果验证结论与报告。', [CAP.DATA, CAP.DOC]],
                ['最佳实践案例助手', '将已完成改善报告提炼为标准案例，实现结构化沉淀、检索复用和相似任务推荐。', [CAP.KB]],
                ['竞品对标与目标建议', '检索主要竞品质量指标与动态，提取关键指标进行对比并生成对标分析报告。', [CAP.SEARCH, CAP.DOC]]
            ])
        }
    };

    const subagentIndex = {};
    Object.keys(workspaces).forEach(function (workspaceId) {
        const workspace = workspaces[workspaceId];
        workspace.id = workspaceId;
        workspace.subagents.forEach(function (subagent) {
            subagent.workspaceId = workspaceId;
            subagent.workspaceName = workspace.name;
            subagentIndex[subagent.id] = subagent;
        });
    });

    window.SUBAO_WORKSPACE_CONFIG = workspaces;
    window.SUBAO_SUBAGENT_INDEX = subagentIndex;
    window.SUBAO_WORK_METHOD = {
        phaseOne: '以导入智能体知识库、数据分析与可视化导出为主要工作方式；知识库尽可能汇集公司及行业专业文件，例如体系文件、报告、失效模式库和标准条款，形成公司级内部记忆。',
        phaseTwo: [
            '与 MES、QMS、ERP 等系统集成，可通过 MCP 或 API 扩展，后续升级为自动读取系统数据。',
            '实时在线 SPC 监控，需要直连 PLC 或 MES 数据流。',
            '机器视觉或 AI 外观检测，需要相机硬件与边缘推理部署。',
            '测量设备数据自动采集（三坐标、扭矩枪、气密仪直连），需要配套电子化设备。'
        ]
    };
})();
