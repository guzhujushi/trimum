# trimum 鈥?AI Process Runtime

> **鎶?AI Agent 鍙樻垚鎿嶄綔绯荤粺绾ц兘鍔涖€?*
> 涓€涓窇鍦?Linux 涓婄殑 AI 鍩虹璁炬柦锛孉gent 鏂囦欢鍖栥€乀ool 鎻掍欢鍖栥€乄orkflow 鍙紪鎺掋€侀殢鐢ㄩ殢鍚笉鍗犺祫婧愩€?
---

## 鐢熸€佷綅缃?
**trimum 鏄洰鍓嶅敮涓€鐢?Python 鍐欑殑 AI 杩涚▼杩愯鏃讹紙Harness锛夈€?*

甯傞潰涓婂凡鏈夌殑绫讳技妗嗘灦鈥斺€擲emaClaw (TS, 83鈽?銆乻kelm (TS, 0鈽?銆丼andcastle (TS, 7780鈽?鈥斺€斿叏閮ㄤ娇鐢?TypeScript銆侺angChain / CrewAI 铏芥槸 Python锛屼絾瀹冧滑涓嶆槸 Harness锛堟槸 Agent 妗嗘灦/缂栨帓灞傦級銆侾ython 鐢熸€侀噷娌℃湁浜哄湪鍋?**"Agent 鐨勬搷浣滅郴缁熷唴鏍?** 杩欎釜灞傜骇鐨勪骇鍝併€?
璇︾粏鍒嗘瀽锛歚docs/ECOSYSTEM-COMPARISON.md`

---

## 鉁?浜偣閫熻

| 浜偣 | 涓€鍙ヨ瘽 |
|---|---|
| **鏋佽嚧杞婚噺鍖?* | 鑳戒笉鐢?Agent 灏变笉鐢ㄢ€斺€旂函鎵ц璧?Tool锛屾湁鍐崇瓥鎵嶇敤 Agent锛屾嫆缁濊繃搴﹁璁?|
| **Transform 棰勭炕璇?* | 鑷劧璇█ 鈫?鏍囧噯鍖栨爣绛捐瑷€锛屾墍鏈夊叆鍙ｇ粺涓€褰掍竴鍖栵紝Workflow 鍙洃鐫?|
| **Workflow 鍏堜簬 LLM** | 浼樺厛鏌ラ缃?workflow锛?0% 閲嶅鎿嶄綔锛夛紝鏈懡涓墠璋?LLM Router |
| **寮规€ф矙绠?* | Security Agent 鍐崇瓥 + Behavior Monitor + Policy Engine锛屽彲閫夌‖鎬?寮规€?鏅鸿兘 |
| **涓夐噸璁板繂浣撶郴** | Agent 绉佹湁璁板繂 / 椤圭洰鍏变韩涓婁笅鏂?/ Planner 鍏ㄥ眬涓婁笅鏂囷紝FTS5 鍏ㄦ枃妫€绱?|
| **System Monitor** | CPU/GPU/Disk/RAM 瀹炴椂鐩戝惉锛屽紓甯稿彂 Event Bus 閫氱煡 |
| **Agent 鏂囦欢鍖?* | Agent = 涓€涓洰褰?+ `trimum-agent.toml`锛宭s 鍙戠幇鎵€鏈夎祫婧愶紝cp 鍗冲畨瑁?|
| **Tool 鎻掍欢鍖?* | 宸ュ叿娉ㄥ唽/鍙戠幇/璋冪敤缁熶竴绠＄悊锛?4 绉嶅師鐢?Dispatcher |
| **Event Bus 鏍囧噯鍖栭€氫俊** | Agent/Workflow/Runtime/Security 缁熶竴浜嬩欢鎬荤嚎锛屽紓姝?pub/sub |
| **AI Runtime 闅忕敤闅忓惎** | 瀹堟姢杩涚▼甯搁┗涓嶅崰璧勬簮锛孉gent 鎸夐渶鍚姩鐢ㄥ畬鍗抽噴鏀?|
| **CLI 鍛戒护缁戝畾** | `trm "鏌ョ湅纾佺洏"` 鈥?鑷劧璇█鐩存帴缁戝畾绯荤粺鎿嶄綔 |
| **寮€绠卞嵆鐢ㄧ殑妗岄潰** | 22 濂?Hyprland 涓婚棰勮 + 涓婚鍒囨崲鍣?+ 涓€閿畨瑁呰剼鏈?|
| **鍏ㄥ寮€鍙戣€呭伐鍏烽摼** | Agent Registry銆丷outer銆乄orkflow Engine銆丆LI client 寮€绠卞嵆鐢?|
| **鏂扮敓鎬?* | Agent/Tool/Workflow 鍏ㄩ儴鏂囦欢鍖栵紝绗笁鏂规墿灞曞嵆鎷峰嵆鐢?|

---

## 鏍稿績鏋舵瀯

```
鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?            鐢ㄦ埛鍏ュ彛 (CLI/WebChat/TUI)            鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                     鈹?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?             Transform Agent (棰勭炕璇戝眰)            鈹?鈹?    鑷劧璇█ 鈫?鏍囧噯鍖栨爣绛捐瑷€(key:value key:value)  鈹?鈹?    鎵€鏈夊叆鍙ｇ粺涓€褰掍竴鍖栵紝Workflow 鍙洃鐫ｅ尮閰?         鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                     鈹?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?           Workflow Engine (+ Listener)           鈹?鈹? 鐩戝惉 Event Bus锛屽尮閰嶉缃?workflow锛?0% 閲嶅鎿嶄綔锛? 鈹?鈹? 鍛戒腑 鈫?鐩存帴鎵ц锛堢渷 LLM 璋冪敤锛?                   鈹?鈹? 鏈懡涓?鈫?杞?Router 鈫?Planner                    鈹?鈹斺攢鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?     鈹?              鈹?              鈹?鈹屸攢鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹?  鈹屸攢鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹?  鈹屸攢鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹? Agent   鈹?  鈹? Security  鈹?  鈹? External    鈹?鈹? Routing 鈹?  鈹?  Agent    鈹?  鈹? Ecosystem   鈹?鈹?         鈹?  鈹?           鈹?  鈹?             鈹?鈹?Router 鈫?鈹?  鈹?寮规€ф矙绠?   鈹?  鈹?3rd Agent    鈹?鈹?Planner  鈹?  鈹?鍐崇瓥涓績    鈹?  鈹?3rd Tool     鈹?鈹?Agent    鈹?  鈹?Behavior   鈹?  鈹?3rd Workflow 鈹?鈹?瀛怉gent  鈹?  鈹?Monitor    鈹?  鈹?             鈹?鈹?璺敱     鈹?  鈹?Landlock   鈹?  鈹?             鈹?鈹斺攢鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹?  鈹斺攢鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹?  鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹?     鈹?              鈹?                鈹?     鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?                     鈹?鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹粹攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?                Harness Runtime                   鈹?鈹?                                                  鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?鈹? 鈹?Agent Mgr  鈹? 鈹? Event Bus   鈹? 鈹?Tool      鈹?鈹?鈹? 鈹?鐢熷懡鍛ㄦ湡   鈹? 鈹? pub/sub     鈹? 鈹?Gateway   鈹?鈹?鈹? 鈹?Socket閫氫俊 鈹? 鈹?绯荤粺浜嬩欢     鈹? 鈹?14 绉?    鈹?鈹?鈹? 鈹?Spawn/     鈹? 鈹?Agent閫氫俊    鈹? 鈹?Dispatcher鈹?鈹?鈹? 鈹?Destroy    鈹? 鈹?             鈹? 鈹?          鈹?鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹?鈹? 鈹?涓夐噸璁板繂             鈹? 鈹?System Monitor   鈹? 鈹?鈹? 鈹? Agent绉佹湁 (no confirm)鈹? 鈹?CPU/GPU/Disk/RAM 鈹? 鈹?鈹? 鈹? 椤圭洰鍏变韩 (闇€纭)    鈹? 鈹?闃堝€煎憡璀?        鈹? 鈹?鈹? 鈹? 鍏ㄥ眬 Planner        鈹? 鈹?Event Bus 閫氱煡   鈹? 鈹?鈹? 鈹? SQLite FTS5 鍏ㄦ枃妫€绱?鈹? 鈹?                 鈹? 鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹? 鈹?鈹? 鈹屸攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹?鈹? 鈹?Shell / Git / HTTP / Process / System   鈹?   鈹?鈹? 鈹?Env / File / Knowledge / Notification   鈹?   鈹?鈹? 鈹?MCP / Custom / Policy / IPC             鈹?   鈹?鈹? 鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?   鈹?鈹斺攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹?```

---

## 鏍稿績缁勪欢

| **Harness Runtime** | AI 杩涚▼杩愯鏃躲€傜鐞?Agent 鐢熷懡鍛ㄦ湡銆佹潈闄愩€佽祫婧愬垎閰嶃€?| 鉁?|
| **Transform Agent** | 鑷劧璇█ 鈫?鏍囧噯鍖栨爣绛捐瑷€锛屾墍鏈夊叆鍙ｇ粺涓€褰掍竴鍖?| 馃摑 寰呭疄鐜?|
| **Workflow Engine** | 鐩戝惉 Event Bus锛屽尮閰嶉缃?workflow锛屼紭鍏堣蛋缂撳瓨鐪?LLM | 鉁?+ 鎵╁睍 |
| **Agent Router** | 鏍规嵁浠诲姟绫诲瀷銆佽兘鍔涘尮閰嶅瓙 Agent锛屾敮鎸佺閬撴瀯寤?| 鉁?|
| **Planner Agent** | Workflow 鏈懡涓椂鐨?LLM 鍏滃簳瑙勫垝 | 鉁?|
| **Security Agent** | 寮规€ф矙绠卞喅绛栦腑蹇冦€傚彲閫夌‖鎬?寮规€?鏅鸿兘妯″紡 | 鉁?Phase 3 |
| **Behavior Monitor** | 鎿嶄綔鍘嗗彶杩借釜銆侀鐜囧紓甯告娴嬨€佽法娌欑妫€娴?| 鉁?Phase 3 |
| **Event Bus** | Agent/Workflow/Runtime/Security 缁熶竴浜嬩欢鎬荤嚎 | 鉁?|
| **Tool Gateway** | 14 绉嶅師鐢?Dispatcher锛岀粺涓€娉ㄥ唽/鍙戠幇/璋冪敤 | 鉁?|
| **Agent Manager** | Agent 杩涚▼鐢熷懡鍛ㄦ湡锛圫ocket 閫氫俊鍚仠锛?| 鉁?Phase 3 |
| **涓夐噸璁板繂** | Agent 绉佹湁 / 椤圭洰鍏变韩 / 鍏ㄥ眬 Planner锛孎TS5 鍏ㄦ枃妫€绱?| 鉁?Phase 3 |
| **System Monitor** | CPU/GPU/Disk/RAM 瀹炴椂鐩戝惉 + Event Bus 閫氱煡 | 鉁?Phase 3 |
| **Policy Engine** | 姝ｅ垯瑙勫垯鍖归厤锛孉ction.CONFIRM 鏀寔 | 鉁?|
| **Context Manager** | SQLite 鎸佷箙鍖栦笂涓嬫枃瀛樺偍 | 鉁?+ 鎵╁睍 |
| **IPC Handler** | JSON-RPC 2.0 over Unix Socket | 鉁?|
| **API Server** | FastAPI HTTP 鎺ュ彛 | 鉁?|

---

## 寮€婧愬弬鑰冧笌鑷磋阿

trimum 鐨勮璁℃繁鍙椾互涓嬪紑婧愰」鐩惎鍙戯細

| 椤圭洰 | 鍊熼壌鍐呭 |
|---|---|
| **[SemaClaw](https://github.com/midea-ai/SemaClaw)** 鈥?涓汉 AI Agent 妗嗘灦锛圱S锛?| DAG Teams 涓ら樁娈电紪鎺掋€丳lugin Marketplace 姒傚康銆佷笁閲嶄笂涓嬫枃绠＄悊鎬濊矾 |
| **[skelm](https://github.com/skelm-framework/skelm)** 鈥?瀹夊叏 Workflow 妗嗘灦锛圱S锛?| Default-Deny 鏉冮檺妯″瀷璁捐銆丳er-Agent Workspace 闅旂鎬濊矾銆乀amper-Evident Audit 鐞嗗康 |
| **[Warp](https://github.com/warpdotdev/Warp)** 鈥?AI 缁堢锛圧ust锛?| TARL 鏍囩璇█鐞嗗康銆丠andoff Snapshot 鏈€灏忎笂涓嬫枃鍘熷垯銆丷un State 鎵╁睍鍚彂 |
| **[Sandcastle](https://github.com/mattpocock/sandcastle)** 鈥?娌欑缂栫爜 Agent锛圱S锛?| 娌欑闅旂璁捐鍙傝€?|

璇︾粏瀵规瘮鍒嗘瀽锛歚docs/ECOSYSTEM-COMPARISON.md`

## 璁捐鍝插

| 闂 | 鏂规 |
|---|---|
| 涓嶆兂姣忔閲嶅鎿嶄綔閮借皟 LLM | Workflow Engine 缂撳瓨棰勭疆娴佺▼锛屽厛鍖归厤鍐?LLM |
| 鑷劧璇█缈昏瘧涓嶇ǔ瀹?| Transform Agent 鏍囧噯鍖栨爣绛捐瑷€杈撳嚭 |
| Agent 浜掔浉璁块棶涓嶅彈鎺?| Security Agent 鍐崇瓥涓績锛岃法宸ュ叿闇€纭 |
| 涓嶇煡閬撶郴缁熸槸鍚︽甯?| System Monitor 瀹炴椂閲囬泦 + Event Bus 鍙戝竷 |
| 璁板繂鏁ｈ惤鍦ㄥ悇涓?Agent | 涓夐噸璁板繂浣撶郴锛孎TS5 缁熶竴妫€绱?|
| Agent 闂存病娉曢€氫俊 | Event Bus pub/sub |
| 涓嶇煡閬撳摢涓?Agent 鑳藉共浠€涔?| Agent Router 鑳藉姏璺敱 |
| 姣忎釜 Agent 閮借鑷繁绠＄悊鏉冮檺 | Security Agent 缁熶竴绛栫暐 |
| 鎯崇紪鎺掑涓?Agent 鍗忎綔 | Workflow Engine |
| 姣忎釜 Agent 閮借鑷繁鍐欏伐鍏疯皟鐢?| Tool Gateway 缁熶竴娉ㄥ唽/鍙戠幇 |
| 绯荤粺婊氭寕浜嗘病浜虹 | Rollback System 鑷姩蹇収+鍥炴粴 |
| Agent 澶噧鑲?| 涓€鍒囩殕鏂囦欢锛宭s 鍙戠幇鍏ㄩ儴锛岄殢鐢ㄩ殢鍚?|

---

## 寮€鍙戠姸鎬?
| Phase | 鍐呭 | 鐘舵€?|
|---|---|---|
| **Phase 0** | 鍩虹鐜 | 鉁?|
| **Phase 1** | AI Shell MVP | 鉁?|
| **Phase 1.5** | 妗岄潰棰勮锛圚yprland 涓婚锛?| 鉁?|
| **Phase 2** | **Harness Runtime Core** 鈥?23 妯″潡 | 鉁?|
| **Phase 2.5** | **Tool Dispatcher 閲嶆瀯** 鈥?14 绉嶅師鐢?Dispatcher | 鉁?|
| **Phase 3** | **寮规€ф矙绠变綋绯?*锛圫ecurity Agent + Behavior Monitor + System Monitor + 涓夐噸璁板繂 + Agent Socket + Workflow v2锛?| 鉁?|
| **Phase 4** | Security Runtime锛圠andlock LSM + Namespace + Seccomp锛?| 馃摑 璁捐 |
| **Phase 5** | Memory Layer锛坈hroma 鍚戦噺搴?+ 鐭ヨ瘑鍥捐氨锛?| 馃摑 璁捐 |
| **Phase 6** | ISO / 涓€閿畨瑁呴暅鍍?| 鈴?|

---

## 椤圭洰缁撴瀯

```
trimum/
鈹溾攢鈹€ README.md
鈹溾攢鈹€ LICENSE
鈹溾攢鈹€ STATUS.md
鈹溾攢鈹€ src/trimum_core/     # Core Runtime锛?3 涓ā鍧楋級
鈹?  鈹溾攢鈹€ agent_registry.py     Agent 绫诲瀷娉ㄥ唽琛?鈹?  鈹溾攢鈹€ agent_router.py       Agent 鑳藉姏璺敱 + 绠￠亾
鈹?  鈹溾攢鈹€ agent_runtime.py      瀛?Agent 杩涚▼鐢熷懡鍛ㄦ湡绠＄悊
鈹?  鈹溾攢鈹€ agent_socket.py       Unix Socket 閫氫俊灞?鈹?  鈹溾攢鈹€ behavior_monitor.py   琛屼负鍩虹嚎 + 寮傚父妫€娴?鈹?  鈹溾攢鈹€ planner_agent.py      鍚?LLM 鏅鸿兘鐨勮鍒?Agent
鈹?  鈹溾攢鈹€ security_agent.py     寮规€ф矙绠卞喅绛栦腑蹇?鈹?  鈹溾攢鈹€ system_monitor.py     CPU/GPU/Disk/RAM 瀹炴椂鐩戝惉
鈹?  鈹溾攢鈹€ workflow_engine.py    DAG 浠诲姟缂栨帓 + v2 鐩戝惉鍣ㄢ啋鎵ц缁?鈹?  鈹溾攢鈹€ tool_gateway.py       宸ュ叿娉ㄥ唽/鍙戠幇/鏉冮檺鏍￠獙
鈹?  鈹溾攢鈹€ tool_dispatchers.py   14 绉嶅師鐢?Dispatcher
鈹?  鈹溾攢鈹€ event_bus.py          寮傛 pub/sub 浜嬩欢鎬荤嚎
鈹?  鈹溾攢鈹€ context_manager.py    涓夐噸璁板繂 + FTS5 鍏ㄦ枃鎼滅储
鈹?  鈹溾攢鈹€ agent_manager.py      Agent 鐢熷懡鍛ㄦ湡绠＄悊
鈹?  鈹溾攢鈹€ policy_engine.py      姝ｅ垯绛栫暐寮曟搸
鈹?  鈹溾攢鈹€ api_server.py         FastAPI HTTP 鎺ュ彛
鈹?  鈹溾攢鈹€ ipc_handler.py        JSON-RPC over Unix Socket
鈹?  鈹溾攢鈹€ main.py               瀹堟姢杩涚▼鍏ュ彛
鈹?  鈹溾攢鈹€ trimum_client.py      CLI 瀹㈡埛绔?鈹?  鈹溾攢鈹€ models.py             Pydantic 鏁版嵁妯″瀷
鈹?  鈹溾攢鈹€ config.py             YAML 閰嶇疆鍔犺浇
鈹?  鈹斺攢鈹€ logger.py             缁撴瀯鍖栨棩蹇?鈹溾攢鈹€ desktop/themes/        # 22 濂?Hyprland 涓婚棰勮
鈹溾攢鈹€ docs/                  # 鏋舵瀯/璺嚎鍥炬枃妗?鈹斺攢鈹€ scripts/               # 瀹夎/杩愮淮鑴氭湰
```

---

## 蹇€熷紑濮?
### 宸叉湁 Arch 绯荤粺

```bash
pip install trimum-core
systemctl --user start trimum-core
trm "鏌ョ湅纾佺洏绌洪棿"
```

### 鍏ㄦ柊瀹夎

```bash
curl -fsSL https://get.trimum.sh | bash
```

锛堥渶 Arch Linux锛岃嚜鍔ㄩ厤缃?Hyprland 妗岄潰 + trimum Core锛?
---

## 璁稿彲

MIT License 鈥?Copyright (c) 2026 guzhujushi
