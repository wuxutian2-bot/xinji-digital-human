"""Nature-inspired AIC figures; Python 3.14. Source values are read, never simulated."""
from pathlib import Path
import json, csv, hashlib, sys
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd()
OUT = ROOT/'output/AIC2026/科研绘图版/科研图件'
DATA = OUT/'source_data'
OUT.mkdir(parents=True, exist_ok=True); DATA.mkdir(exist_ok=True)
MODEL = Path(r'D:\模型微调')
SOURCES = {
 'sft_build': MODEL/'outputs/qwen4b_large_v1_r1/data_build_report.json',
 'orpo_build': MODEL/'data/processed/orpo_preferences/build_report.json',
 'sft_train': MODEL/'outputs/qwen4b_large_v1_r1/adapter/trainer_state.json',
 'orpo_train': MODEL/'outputs/qwen4b_orpo_qlora/adapter/trainer_state.json',
 'decision': ROOT/'logs/decision-b-cpu-schema-r1.json',
 'daily': ROOT/'logs/phase-d-daily-comparison-final.json',
 'engineering': ROOT/'logs/evaluation/engineering.json',
 'no_memory': ROOT/'logs/evaluation/no-memory.json',
 'no_expression': ROOT/'logs/evaluation/no-expression.json',
 'tts': ROOT/'logs/expression_tts.json',
 'architecture': ROOT/'src/open_llm_vtuber/agent/agents/mental_health_agent.py',
 'daily_method': ROOT/'docs/mental_health_phase_d_results.md',
}
def writejson(p,j): p.write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8')
J={k:json.loads(p.read_text(encoding='utf-8')) for k,p in SOURCES.items() if p.suffix=='.json'}
writejson(DATA/'source_manifest.json', {k:{'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for k,p in SOURCES.items()})
contracts=[
 ('fig1_architecture','系统以状态、意愿、安全约束协调数字人回应','mechanism_overview','architecture','代码结构示意，无统计推断'),
 ('fig2_daily_method','daily_v2 按来源和有效日形成可用于决策的历史证据','mechanism_workflow','daily_method','算法示意；7日窗口与3日门槛为配置值'),
 ('fig3_daily_evidence','日等权及来源分层改变统计解释，精确重放不改变统计','paired_quantification','daily','6个固定合成案例；a/b分别展示2个案例；无随机重复或推断检验'),
 ('fig4_data','两条训练路线各自保留数据筛选和分割记录','flow_and_distribution','sft_build,orpo_build','样本/偏好对计数；完整数据集，无误差线'),
 ('fig5_training','两条独立适配路线均有可追溯的训练与验证轨迹','quantitative_grid','sft_train,orpo_train','每条路线一次训练；原始日志点、不平滑；验证集128条/64对；loss目标不同'),
 ('fig6_runtime','固定协议实验具有可测量的时延及整机资源范围','hero_and_support','decision','6场景×3轮=18请求；固定顺序无预热；158次资源采样；分位数沿用原日志定义'),
 ('fig7_ablation','记忆、表达开关及语速参数均进入系统执行链','mechanism_and_quantification','engineering,no_memory,no_expression,tts','固定合成输入组件消融；每个TTS速度一条音频，无重复与误差线'),
]
writejson(OUT/'figure_contract.json',{'backend':'Python 3.14 / Matplotlib','style':'Nature-inspired, not a journal compliance certification','author_width_mm':180,'report_width_mm':150,'exports':['editable SVG','vector PDF','600 dpi PNG'],'statistics':'No invented p-values, confidence intervals, participant data or clinical effects.','figures':[dict(zip(['id','claim','archetype','sources','statistical_scope'],r)) for r in contracts]})

BLUE='#4B7D9B'; TEAL='#438F83'; PURPLE='#8875AD'; CORAL='#CD8175'; GRAY='#77828A'; INK='#273640'
PALE_BLUE='#E8F0F5'; PALE_TEAL='#E7F1ED'; PALE_PURPLE='#EFEBF5'; PALE_CORAL='#F7ECE8'
plt.rcParams.update({'font.family':['Arial','Microsoft YaHei'],'font.size':10,'axes.titlesize':11,'axes.labelsize':10,'xtick.labelsize':9,'ytick.labelsize':9,'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,'axes.edgecolor':INK,'text.color':INK,'axes.labelcolor':INK,'xtick.color':INK,'ytick.color':INK,'svg.fonttype':'none','pdf.fonttype':42,'savefig.facecolor':'white','axes.unicode_minus':False})
QA=[]
def csvout(name,rows):
 with (DATA/name).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def fig(h=100):return plt.figure(figsize=(180/25.4,h/25.4),facecolor='white')
def save(f,name):
 f.canvas.draw();renderer=f.canvas.get_renderer();outside=[]
 for t in f.findobj(matplotlib.text.Text):
  if t.get_visible() and t.get_text():
   b=t.get_window_extent(renderer)
   if b.x0 < -1 or b.y0 < -1 or b.x1 > f.bbox.width+1 or b.y1 > f.bbox.height+1: outside.append(t.get_text())
 QA.append({'figure':name,'text_outside_canvas':outside})
 for ext in ['svg','pdf','png']: f.savefig(OUT/f'{name}.{ext}',dpi=600)
 f.savefig(OUT/f'{name}-preview.png',dpi=170)
 plt.close(f)
def panel(ax,letter,title):
 ax.text(-.02,1.075,letter,transform=ax.transAxes,fontweight='bold',fontsize=12,va='bottom')
 ax.text(.05,1.075,title,transform=ax.transAxes,fontsize=10,va='bottom')
def box(ax,x,y,w,h,title,subtitle='',color=PALE_BLUE,edge=BLUE,size=10):
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.005,rounding_size=0.015',facecolor=color,edgecolor=edge,lw=.8))
 ax.text(x+w/2,y+h*(.65 if subtitle else .5),title,ha='center',va='center',fontsize=size,fontweight='bold')
 if subtitle:ax.text(x+w/2,y+h*.27,subtitle,ha='center',va='center',fontsize=size-1,color=INK)
def arrow(ax,a,b,color=GRAY,style='-',rad=0):
 ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=10,lw=.85,color=color,linestyle=style,connectionstyle=f'arc3,rad={rad}'))

# 1. A readable mechanism diagram, with the risk bypass kept explicit.
f=fig(107);a=f.add_axes([.015,.015,.97,.97]);a.set(xlim=(0,1),ylim=(0,1));a.axis('off')
a.text(.015,.965,'a',fontsize=12,fontweight='bold');a.text(.055,.965,'从当前输入到策略与表达',fontsize=11,fontweight='bold')
box(a,.02,.70,.18,.15,'用户输入','文字 / ASR')
box(a,.27,.70,.18,.15,'Safety','输入风险检查',PALE_CORAL,CORAL)
box(a,.53,.70,.20,.15,'State + Intent','当前状态 / 明确诉求',PALE_TEAL,TEAL)
box(a,.79,.70,.19,.15,'历史证据','分来源的跨日统计',PALE_PURPLE,PURPLE)
arrow(a,(.20,.775),(.27,.775));arrow(a,(.45,.775),(.53,.775));arrow(a,(.79,.775),(.73,.775),PURPLE)
box(a,.29,.40,.24,.17,'Decision + 协调器','提议 → 校验 → 最终策略',PALE_TEAL,TEAL)
box(a,.61,.40,.19,.17,'Dialogue','受策略约束的生成')
box(a,.84,.40,.14,.17,'输出检查','放行 / 改写',PALE_CORAL,CORAL,size=9.5)
arrow(a,(.63,.70),(.42,.57));arrow(a,(.53,.485),(.61,.485));arrow(a,(.80,.485),(.84,.485))
box(a,.02,.40,.19,.17,'风险升级路径','固定支持与求助提示',PALE_CORAL,CORAL,size=9.5)
arrow(a,(.31,.70),(.115,.57),CORAL)
box(a,.71,.10,.27,.15,'Expression + 数字人','语音 / 表情 / 动作 / 注视',PALE_BLUE,BLUE)
box(a,.29,.10,.32,.15,'状态与决策轨迹','策略依据 / 协调原因 / 执行结果',PALE_PURPLE,PURPLE)
arrow(a,(.91,.40),(.86,.25));arrow(a,(.71,.175),(.61,.175),PURPLE)
arrow(a,(.115,.40),(.115,.32),CORAL);arrow(a,(.115,.32),(.845,.32),CORAL);arrow(a,(.845,.32),(.845,.25),CORAL)
a.text(.015,.03,'b',fontsize=12,fontweight='bold');a.text(.055,.03,'回放入口：固定输入与历史 → 切换组件 → 比较决策和实际执行',fontsize=9.5)
a.text(.43,.62,'普通流程',fontsize=8.5,color=GRAY);a.text(.075,.28,'绕过两个模型',fontsize=8.5,color=CORAL)
save(f,'fig1_architecture')

# 2. Daily aggregation and observation eligibility.
f=fig(97);a=f.add_axes([.02,.02,.96,.96]);a.set(xlim=(0,1),ylim=(0,1));a.axis('off')
a.text(.015,.955,'a',fontsize=12,fontweight='bold');a.text(.06,.955,'按本地日历划分两个连续窗口',fontsize=11,fontweight='bold')
for i in range(14):
 x=.04+i*.066;a.add_patch(Rectangle((x,.74),.059,.115,fc=PALE_PURPLE if i<7 else PALE_TEAL,ec='white'))
 a.text(x+.0295,.795,str(i-13),ha='center',va='center',fontsize=9)
a.text(.25,.89,'前期 7 日',ha='center',color=PURPLE);a.text(.72,.89,'当前 7 日',ha='center',color=TEAL)
a.text(.97,.70,'参考日 = 0；只纳入截至参考时刻的记录',ha='right',fontsize=8.7,color=GRAY)
a.text(.015,.64,'b',fontsize=12,fontweight='bold');a.text(.06,.64,'按来源聚合，保留缺失与新鲜度',fontsize=11,fontweight='bold')
for y,title,c,e in [(.43,'系统估计',PALE_BLUE,BLUE),(.265,'用户自报',PALE_TEAL,TEAL),(.10,'用户纠正',PALE_PURPLE,PURPLE)]:
 box(a,.04,y,.16,.11,title,color=c,edge=e,size=9.5)
 arrow(a,(.20,y+.055),(.27,y+.055),e)
 box(a,.27,y,.19,.11,'去重 → 日均',color=c,edge=e,size=9.5)
 arrow(a,(.46,y+.055),(.53,y+.055),e)
 box(a,.53,y,.18,.11,'有效日等权',color=c,edge=e,size=9.5)
 arrow(a,(.71,y+.055),(.77,y+.055),e)
box(a,.77,.10,.20,.44,'进入决策的门槛','每维至少 3 日\n最近观测 ≤ 7 日\n不足或过期 → null',color='#F4F5F6',edge=GRAY,size=9)
a.text(.5,.02,'分别输出：均值、跨窗变化、有效日数、覆盖率与来源；零分与未知分开',ha='center',fontsize=9)
save(f,'fig2_daily_method')

# 3. Deterministic synthetic comparisons read from the frozen replay JSON.
cases={c['case']:c for c in J['daily']['cases']}
u=cases['unequal_daily_frequency'];s=cases['separate_sources']
v=[u['rolling_v1']['means']['stress'],u['daily_v2']['sources']['system_estimate']['dimensions']['stress']['mean']]
v2=[s['rolling_v1']['means']['stress'],s['daily_v2']['sources']['system_estimate']['dimensions']['stress']['mean'],s['daily_v2']['sources']['user_report']['dimensions']['stress']['mean']]
csvout('daily_comparison.csv',[{'case':u['case'],'statistic':'record_weighted','value':v[0]},{'case':u['case'],'statistic':'daily_equal','value':v[1]},{'case':s['case'],'statistic':'mixed_sources','value':v2[0]},{'case':s['case'],'statistic':'system_estimate','value':v2[1]},{'case':s['case'],'statistic':'user_report','value':v2[2]}])
csvout('daily_replay_checks.csv',[{'case':c['case'],'exact_replay_invariant':c['exact_replay_invariant']} for c in J['daily']['cases']])
f=fig(96);axes=[f.add_axes([.09,.28,.36,.53]),f.add_axes([.60,.28,.36,.53])]
for ax,vals,labels,colors,letter,title in [(axes[0],v,['按记录','按日等权'],[GRAY,TEAL],'a','降低单日高频观测的权重'),(axes[1],v2,['混合来源','系统估计','用户自报'],[GRAY,BLUE,TEAL],'b','保留不同来源的独立含义')]:
 x=np.arange(len(vals));ax.bar(x,vals,color=colors,width=.5,alpha=.85);ax.scatter(x,vals,s=15,color=colors,zorder=3)
 ax.set(ylim=(0,1.02),xticks=x,xticklabels=labels,ylabel='压力状态均值 (0–1)');ax.set_yticks([0,.5,1]);panel(ax,letter,title)
 for i,y in enumerate(vals):ax.text(i,y+.04,f'{y:.3f}',ha='center',fontsize=10)
axes[0].text(.5,-.26,'3 个有效日：30×1、1×0、1×0',transform=axes[0].transAxes,ha='center',fontsize=8.5)
axes[1].text(.5,-.26,'系统与自报各 3 日：0.8 与 0',transform=axes[1].transAxes,ha='center',fontsize=8.5)
f.text(.5,.045,'6 / 6 合成案例：追加 100 条完全相同记录后，分来源统计保持不变',ha='center',fontsize=10,color=TEAL)
save(f,'fig3_daily_evidence')

# 4. Training data lineage plus complete category distribution.
b=J['sft_build']['counts'];o=J['orpo_build']
csvout('sft_counts.csv',[{'stage':k,'count':v} for k,v in b.items()]);csvout('orpo_categories.csv',[{'category':k,'count':v} for k,v in o['categories'].items()])
f=fig(105);a=f.add_axes([.02,.04,.43,.80]);a.set(xlim=(0,1),ylim=(0,1));a.axis('off');panel(a,'a','SFT 数据构建')
box(a,.17,.76,.66,.13,'候选语料  4,096 条',color=PALE_BLUE)
box(a,.17,.49,.66,.13,'筛选保留  3,379 条',color=PALE_TEAL,edge=TEAL)
box(a,.17,.16,.66,.14,'最终训练  3,423 条',color=PALE_PURPLE,edge=PURPLE)
arrow(a,(.5,.76),(.5,.62));arrow(a,(.5,.49),(.5,.30))
a.text(.53,.68,'移出 717 条',fontsize=9,color=GRAY)
a.text(.53,.39,'加入目标轮次 44 条',fontsize=9,color=PURPLE)
a.text(.5,.065,'冻结验证集 128 条',ha='center',fontsize=10)
ax=f.add_axes([.66,.17,.29,.67]);panel(ax,'b','ORPO 偏好对构成')
names={'ordinary_support':'普通支持','uncertainty':'事实不确定性','user_boundary':'用户边界','diagnosis':'诊断边界','domestic_violence':'家暴边界','self_harm_crisis':'自伤危机边界','concise_closure':'简短收尾'}
items=sorted(o['categories'].items(),key=lambda x:-x[1]);yy=np.arange(len(items))
ax.barh(yy,[v for k,v in items],height=.55,color=[TEAL]+[BLUE]*6,alpha=.82)
ax.set(yticks=yy,yticklabels=[names[k] for k,v in items],xlim=(0,560),xlabel='偏好对数量');ax.invert_yaxis();ax.set_xticks([0,250,500]);ax.spines['left'].set_visible(False);ax.tick_params(axis='y',length=0)
for i,(k,vv) in enumerate(items):ax.text(vv+10,i,str(vv),va='center',fontsize=9)
f.text(.76,.035,'共 640 对：训练 576 / 验证 64',ha='center',fontsize=9.5)
save(f,'fig4_data')

# 5. Actual SciPlot VisualSpec. CSV mappings let the skill verify every plotted point.
panels=[]
for i,name in enumerate(['sft','orpo']):
 state=J[name+'_train']; tr=[{'step':r['step'],'loss':r['loss']} for r in state['log_history'] if 'loss' in r and 'eval_loss' not in r]
 ev=[{'step':r['step'],'loss':r['eval_loss']} for r in state['log_history'] if 'eval_loss' in r]
 csvout(name+'_train.csv',tr);csvout(name+'_validation.csv',ev)
 plots=[]
 for kind,color,label,marker in [('train',BLUE,'训练日志',None),('validation',CORAL,'验证集','o')]:
  plots.append({'type':'line','data':{'source':f'../source_data/{name}_{kind}.csv','mapping':{'x':'step','y':'loss'}},'label':label,'style':{'color':color,'line_width_pt':1.1,**({'marker':marker} if marker else {})}})
 p={'id':'ab'[i],'backend':'matplotlib','bbox_normalized':[.10+i*.49,.22,.36,.64],'representation':'semantic_vector','source_strategy':'raw_data','semantic_role':'quantification','required_output':'svg','answers_question':'训练与验证目标如何随更新步变化？','evidence_ids':[name+'_train'],'plots':plots,'axes':{'x':{'label':'优化步数','limits':[0,880 if i==0 else 220],'ticks':[0,400,800] if i==0 else [0,100,200]},'y':{'label':'SFT loss' if i==0 else 'ORPO loss','limits':[1.8,4.6] if i==0 else [1.8,5.4]}},'legend':{'loc':'upper right','font_size_pt':9,'frameon':False},'annotations':[{'type':'text','coordinate_space':'axes_fraction','coordinates':[0,1.1],'text':('a   SFT  ·  3,423 条训练 / 128 条验证' if i==0 else 'b   ORPO  ·  576 对训练 / 64 对验证'),'style':{'font_size_pt':10,'ha':'left','va':'bottom'}},{'type':'text','coordinate_space':'axes_fraction','coordinates':[.5,-.25],'text':('最佳验证 2.2885 · step 800' if i==0 else '最佳验证 2.7734 · step 200'),'style':{'font_size_pt':9,'ha':'center','va':'top'}}]}
 p['annotations'][0]['text']=('a   SFT 领域适配' if i==0 else 'b   ORPO 偏好优化')
 panels.append(p)
spec={'schema':'scientificfigure.visualspec.v2','figure':{'size_mm':[180,87],'dpi':600,'background':'white','crop_mode':'fixed_canvas'},'theme':{'font':{'family_candidates':['Arial','Microsoft YaHei'],'size_pt':9},'axes':{'line_width_pt':.7}},'layout':{'archetype':'quantitative_grid','target_width_mm':180,'narrative_order':['a','b'],'min_readable_font_size_pt':8,'panel_weights':{'a':1,'b':1}},'panels':panels}
spec['delivery']={'data_columns':{'x':'step','y':'loss'}}
(OUT/'training_sciplot').mkdir(exist_ok=True);writejson(OUT/'training_sciplot/visualspec.json',spec)

# 6. All 18 per-request timings + all resource samples (not process memory).
r=J['decision'];rows=[{'case':c['case'],'round':c['round'],'latency_s':c['latency_ms']/1000} for c in r['cases'] if c.get('latency_ms') is not None];csvout('decision_latency.csv',rows)
rr=r['resources']['samples'];start=datetime.fromisoformat(rr[0]['at'])
res=[{'seconds':(datetime.fromisoformat(s['at'])-start).total_seconds(),'system_ram_gib':s['memory']['used_bytes']/2**30,'gpu_used_mib':s['gpu']['devices'][0]['used_mib']} for s in rr];csvout('decision_resources.csv',res)
f=fig(111);ax=f.add_axes([.10,.20,.42,.64]);panel(ax,'a','CPU Decision 请求时延')
cats=list(dict.fromkeys(c['case'] for c in rows));labels=['问候','工作压力','实际帮助','指令干扰','只想倾诉','结束对话']
for rnd,col,mk in [(1,BLUE,'o'),(2,TEAL,'s'),(3,PURPLE,'^')]:
 vs=[next(c['latency_s'] for c in rows if c['case']==k and c['round']==rnd) for k in cats]
 ax.scatter(np.arange(6)+(rnd-2)*.13,vs,color=col,s=22,marker=mk,label=f'第 {rnd} 轮',zorder=3)
ax.set(xticks=np.arange(6),xticklabels=labels,ylabel='单次请求时延 (s)',ylim=(4.1,6.25));ax.tick_params(axis='x',rotation=33);ax.legend(frameon=False,fontsize=8,ncol=3,loc='upper center',bbox_to_anchor=(.5,-.19),columnspacing=.7,handletextpad=.3)
ax.axhline(r['latency_ms']['p50']/1000,color=GRAY,lw=.8,ls='--');ax.text(5.45,5.20,'P50',ha='right',fontsize=8,color=GRAY)
for bbox,key,unit,col,letter,title,lims in [([.68,.61,.28,.25],'system_ram_gib','整机 RAM (GiB)',TEAL,'b','整机 RAM',(17.5,18.5)),([.68,.17,.28,.27],'gpu_used_mib','GPU 占用 (MiB)',PURPLE,'c','GPU 占用',(5300,5600))]:
 ax=f.add_axes(bbox);ax.plot([s['seconds'] for s in res],[s[key] for s in res],c=col,lw=1.1);ax.set(xlabel='采样时间 (s)',ylabel=unit,ylim=lims);panel(ax,letter,title)
f.text(.31,.94,'18 请求 · 6 场景 × 3 轮',ha='center',fontsize=9.5,color=GRAY)
save(f,'fig6_runtime')

# 7. Mechanism ablation -- qualitative outcomes are categorical, never scored.
def getcase(source,case):return next(c for c in J[source]['cases'] if c['id']==case)
ablation=[{'component':'memory','condition':condition,'outcome':getcase(src,case)['decisions'][0]['strategy']['primary']} for condition,src,case in [('recent_stress','engineering','history_stress'),('disabled','no_memory','history_stress'),('unknown_history','engineering','history_unknown')]]
assert [r['outcome'] for r in ablation]==['reflect_and_clarify','supportive_listening','supportive_listening']
assert getcase('no_expression','history_stress')['actions']==[{}]
ablation.append({'component':'expression','condition':'disabled','outcome':'actions=[{}]'})
csvout('mechanism_ablation.csv',ablation)
tts=J['tts']['rows'];assert [(r['speed'],r['duration_ms']) for r in tts]==[(.8,6648),(1.2,4440)]
csvout('tts_speed.csv',[{'speed':r['speed'],'audio_duration_ms':r['duration_ms']} for r in tts])
f=fig(100);a=f.add_axes([.02,.05,.59,.80]);a.set(xlim=(0,1),ylim=(0,1));a.axis('off');panel(a,'a','固定当前输入，改变历史条件')
for y,l,rgt,col,edge in [(.72,'近期压力历史','反映与澄清',PALE_TEAL,TEAL),(.48,'关闭记忆','支持性倾听',PALE_BLUE,BLUE),(.24,'仅未知历史','支持性倾听',PALE_BLUE,BLUE)]:
 box(a,.03,y,.37,.14,l,color=col,edge=edge,size=9.5);arrow(a,(.40,y+.07),(.57,y+.07));box(a,.57,y,.39,.14,rgt,color=col,edge=edge,size=9.5)
a.text(.50,.09,'关闭表达 → 动作对象为空',ha='center',fontsize=9.5,color=PURPLE)
ax=f.add_axes([.74,.25,.22,.60]);panel(ax,'b','固定文本语速对照')
ax.bar([0,1],[6.648,4.440],color=[BLUE,TEAL],width=.45,alpha=.85);ax.set(xticks=[0,1],xticklabels=['0.8','1.2'],xlabel='TTS 速度设置',ylabel='音频时长 (s)',ylim=(0,8));ax.set_yticks([0,4,8])
for x,y in enumerate([6.648,4.440]):ax.text(x,y+.2,f'{y:.3f}',ha='center',fontsize=9.5)
f.text(.84,.09,'每个设置 1 条音频',ha='center',fontsize=9,color=GRAY)
save(f,'fig7_ablation')
writejson(OUT/'custom_render_qa.json',QA)
print(json.dumps({'output':str(OUT),'figures_custom':len(QA),'canvas_issues':QA},ensure_ascii=False))
