# 鎶€鏈€夊瀷 BOM锛圔ill of Materials锛?

> 鏍规嵁 v1.1 鏋舵瀯鍐荤粨鐨勬妧鏈€夊瀷銆傚鏃犲厖鍒嗙悊鐢憋紝涓嶆洿鏀广€?

## 1. 绯荤粺灞?

| 缁勪欢 | 閫夋嫨 | 鍘熷洜 | 澶囬€?|
|---|---|---|---|
| OS | Arch Linux | 鏋佺畝銆侀€忔槑銆佹粴鍔ㄦ洿鏂拌窡杩?AI 鐢熸€?| Fedora / NixOS |
| Kernel | Linux 6.x+ | Landlock(5.13+) / Seccomp / Namespace 鏀寔 | 鑷紪璇戝唴鏍革紙涓嶉渶瑕侊級 |
| Init | systemd | trmd 浣滀负 systemd 鏈嶅姟绠＄悊 | OpenRC |
| 鏂囦欢绯荤粺 | Btrfs | 蹇収鍥炴粴锛堥槻姝㈡粴鍔ㄦ洿鏂扮偢鏈猴級 | ext4 / ZFS |
| 寮€鍙戝鍣?| Docker | 椤圭洰闅旂銆丄gent 娌欑 | Podman |

## 2. Runtime 灞傦紙trimum Core锛?

> 2026-08-29 鍐崇瓥锛?*鍏ㄧ▼ Python**銆傚師 Rust 璁″垝鍙栨秷銆傜悊鐢憋細Rust 鍥藉唴浼佷笟鐢熸€佷笉瓒炽€丄I 缂栫▼鍔╂墜璁粌鏁版嵁瑕嗙洊宸€乿ibe coding 鎶ラ敊 AI 闅句慨銆侰ore 鐡堕鍦?LLM API 寤惰繜锛堢绾э級锛孭ython 鏁堢巼锛堟绉掔骇锛変笉褰卞搷銆傚叏鏍堢粺涓€ Python 闄嶄綆缁存姢鎴愭湰銆?

| 缁勪欢 | 閫夋嫨 | 鍘熷洜 | 澶囬€?|
|---|---|---|---|
| **璇█** | Python 3.12+ | AI 鐢熸€佷簨瀹炴爣鍑嗐€佸叏鏍堢粺涓€ | 鈥?|
| 寮傛妗嗘灦 | asyncio + aiohttp | Python 鍘熺敓寮傛 | FastAPI (ASGI) |
| HTTP 妗嗘灦 | aiohttp / FastAPI | REST API + WebSocket | Starlette |
| 搴忓垪鍖?| Pydantic v2 + json | 绫诲瀷瀹夊叏銆佷笌 Agent SDK 缁熶竴 | msgspec |
| 鏃ュ織 | structlog | 缁撴瀯鍖栨棩蹇?| loguru |
| 杞婚噺鏁版嵁搴?| SQLite | Phase 2 鍘熷瀷蹇€熷瓨鍌?| 鈥?|
| 鎵╁睍鏁版嵁搴?| PostgreSQL | Phase 3+ 鎸佷箙鍖?| MySQL |
| 缂撳瓨 | Redis | Context 缂撳瓨銆乀ask Queue锛堝彲閫夛級 | 鈥?|
| 瑙勫垯瑙ｆ瀽 | PyYAML + Pydantic | Policy Engine 閰嶇疆 | toml / json |
| 杩涚▼绠＄悊 | systemd | trmd 浣滀负 systemd 鏈嶅姟 | 鈥?|

## 3. Intelligence 灞傦紙Agent SDK锛?

| 缁勪欢 | 閫夋嫨 | 鍘熷洜 | 澶囬€?|
|---|---|---|---|
| 璇█ | Python 3.12+ | AI 鐢熸€佷簨瀹炴爣鍑?| 鈥?|
| 鍖呯鐞?| uv | 鏋佸揩銆佹浛浠?pip+venv | Poetry / PDM |
| 鏁版嵁楠岃瘉 | Pydantic v2 | Agent SDK 鐨?Tool/Context 绫诲瀷瀹氫箟 | msgspec |
| HTTP 瀹㈡埛绔?| httpx | trimum Core API 璋冪敤 | aiohttp |
| 妯″瀷鎶借薄 | LiteLLM | 缁熶竴 OpenAI/Claude/Ollama/DeepSeek 鎺ュ彛 | direct API |
| CLI 妗嗘灦 | Typer | Phase 1 CLI | Click |
| 缁堢 UI | Rich | 鏍煎紡鍖栧伐鍏锋湁鏁堣緭鍑?| textual |
| Runtime 鍩虹 | BaseAgent (鑷爺) | 鎻愪緵 reasoning_loop + tool 娉ㄥ唽鍩哄簳 | LangChain |

## 4. Information 灞傦紙Retrieval Tool锛?

| 缁勪欢 | 閫夋嫨 | 鍘熷洜 | 澶囬€?|
|---|---|---|---|
| 璇█ | Python 3.12+ | 鈥?| 鈥?|
| 鍚戦噺鏁版嵁搴?| PostgreSQL + pgvector | 灏戠淮鎶わ紝涓€涓?DB 瑙ｅ喅 | Qdrant / Chroma |
| Embedding 妯″瀷 | BGE-small / BGE-base | 涓枃浼樼銆佹湰鍦板彲璺?| E5 / GTE |
| 鏂囨。瑙ｆ瀽 | PyMuPDF (PDF) / python-docx (Word) / BeautifulSoup (HTML) | 鈥?| 鈥?|
| 妫€绱㈢紪鎺?| 鑷爺锛堣交閲?200 琛岋級 | Phase 5 涓嶉渶瑕?LlamaIndex 鐨勫鏉傚害 | LlamaIndex |
| 鍏抽敭瀛楁悳绱?| SQLite FTS5 / PostgreSQL tsvector | 鈥?| 鈥?|

## 5. 瀹夊叏灞?

| 缁勪欢 | 閫夋嫨 | 鍘熷洜 | 鍓嶆彁 |
|---|---|---|---|
| LSM | Landlock (Rust landlock crate) | 鏂囦欢绯荤粺璁块棶闄愬埗 | Linux 5.13+ |
| Syscall 杩囨护 | Seccomp | 闄愬埗 Agent 绯荤粺璋冪敤 | 鈥?|
| 闅旂 | Namespace (User/Mount) | 杞婚噺杩涚▼闅旂 | 鈥?|
| 娌欑 | Docker | 楂橀闄╀换鍔″畬鏁撮殧绂?| 宸茶 Docker |
| 闃茬伀澧?| nftables | 缃戠粶璁块棶鎺у埗 | 鈥?|

## 6. 寮€绠卞伐鍏锋竻鍗?

### 閿佸畾锛堝繀瑁咃級

| 宸ュ叿 | 鐗堟湰/鏉ユ簮 | 鐢ㄩ€?|
|---|---|---|
| Systemd | 榛樿 | 鏈嶅姟鐢熷懡鍛ㄦ湡绠＄悊 |
| Rust | rustup stable | 鍙€夆€斺€旈潪 Harness 鎵€闇€锛屼緵鍏朵粬 Rust 椤圭洰浣跨敤 |
| Python | 3.12+ (uv 绠＄悊) | Agent SDK / Retrieval Tool |
| Docker | 鏈€鏂?| Agent 娌欑 + 宸ュ叿閾惧洖婊氫繚闅?|
| Git | 鏈€鏂?| 鐗堟湰鎺у埗 / AI 淇敼璁板綍 |
| ripgrep (rg) | pacman | 蹇€熶唬鐮佹悳绱?|
| fd | pacman | 蹇€熸枃浠舵煡鎵?|
| jq | pacman | JSON 澶勭悊 |
| btop / htop | pacman | 绯荤粺鐩戞帶 |
| Snapper | pacman | Btrfs 蹇収绠＄悊 |
| Landlock (鍐呮牳) | Linux 5.13+ | 鏂囦欢绯荤粺瀹夊叏闄愬埗 |
| Seccomp (鍐呮牳) | 榛樿鍚敤 | 绯荤粺璋冪敤杩囨护 |
| nftables | pacman | 缃戠粶闃茬伀澧?|

### 鍙€夛紙涓夋。妯″紡 + 鑷畾涔夊嬀閫夛級

瀹夎鐣岄潰鎻愪緵涓夋。棰勮妯″紡锛岄€変腑鍚庝粛鍙繘鍏ヨ缁嗗嬀閫夊井璋冿細

| 妯″紡 | 鍐呭 | 纾佺洏 |
|---|---|---|
| 馃専 **鏅€氭ā寮?* | 娴忚鍣?+ 妗岄潰缁勪欢 | ~10-20GB |
| 馃殌 **寮€鍙戣€呮ā寮?* | 鏅€?+ 缂栬緫鍣?AI缂栫爜/Shell澧炲己/鏁版嵁搴?浠ｇ悊 | ~40-60GB |
| 馃И **AI Engineer** | 寮€鍙戣€?+ 鏈湴妯″瀷/GPU/RAG/澶欰gent/DevOps | 100GB+ |

#### 瀹屾暣鍙€夋竻鍗?

| 绫诲埆 | 宸ュ叿 | 鏉ユ簮 | 榛樿妯″紡 |
|---|---|---|---|
| **缂栬緫鍣?* | VS Code (code) | pacman | 寮€鍙戣€? |
| | Cursor | AUR (cursor-bin) | 寮€鍙戣€? |
| | Neovim | pacman | 寮€鍙戣€? |
| **AI 缂栫爜** | Codex CLI | npm 鍏ㄥ眬 | 寮€鍙戣€? |
| | Claude Code | npm 鍏ㄥ眬 | 寮€鍙戣€? |
| **娴忚鍣?* | Firefox | pacman | 鏅€? |
| **缃戠粶浠ｇ悊** | Clash Meta | AUR (clash-meta) | 寮€鍙戣€? |
| | V2rayA | AUR (v2raya-bin) | 寮€鍙戣€? |
| **Shell 澧炲己** | zsh + oh-my-zsh | pacman / AUR | 寮€鍙戣€? |
| | starship | pacman | 寮€鍙戣€? |
| | tmux | pacman | 寮€鍙戣€? |
| | fzf | pacman | 寮€鍙戣€? |
| | zoxide | pacman | 寮€鍙戣€? |
| | eza | pacman | 寮€鍙戣€? |
| **鏁版嵁搴?* | PostgreSQL + pgvector | pacman | AI Engineer |
| | MySQL / MariaDB | pacman | AI Engineer |
| | Redis | pacman | AI Engineer |
| **鏈湴 AI** | Ollama / llama.cpp | pacman / AUR | AI Engineer |
| | GPU CUDA / ROCm | 椹卞姩 | AI Engineer |
| **绯荤粺澧炲己** | Timeshift | pacman | AI Engineer |
| | Ansible | pacman | AI Engineer |
| **妗岄潰缁勪欢** | Waybar | pacman | 鏅€? |
| | Cronie | pacman | 鏅€? |
| | Landlock Hook | Harness 鑷甫 | 鏅€? |
| **Agent 鎵╁睍** | Research Agent | pip | AI Engineer |
| | DevOps Agent | pip | AI Engineer |
| | Teaching Agent | pip | AI Engineer |

### 棰勮 Agent

| Agent | 榛樿鍚敤 | 澶囨敞 |
|---|---|---|
| AI Shell | 鉁?| 鑷劧璇█鈫掑畨鍏ㄦ墽琛?|
| System Healthy | 鉁?| 闃叉粴鎸傝嚜妫€ + 鏇存柊鍚庢鏌?|
| Theme Manager | 鉁?| AI 杈呭姪鍒囨崲妗岄潰涓婚 |
| Security Agent | 鉁?| Landlock Hook + 楂樺嵄鎿嶄綔鎷︽埅 |
| Knowledge Agent | 鉁?| 闀挎湡璁板繂 + 璇箟妫€绱紙Phase 5 鍚敤锛?|
| File Ops | 鉂?| 鍙€夊畨瑁?|
| Coding Agent | 鉂?| 鐢?Codex CLI / Claude Code 鏇夸唬 |

## 7. 纭欢闇€姹?

### Phase 1-2锛堜粎浜戠 LLM锛?

| 缁勪欢 | 鏈€浣?| 鎺ㄨ崘 |
|---|---|---|
| CPU | 4 鏍?| 8 鏍?|
| RAM | 8GB | 16GB |
| 瀛樺偍 | 256GB SSD | 512GB SSD |
| GPU | 涓嶉渶瑕?| 涓嶉渶瑕?|

### Phase 3+锛堟湰鍦版ā鍨嬶級

| 妯″瀷澶у皬 | 鏈€浣?RAM | 鎺ㄨ崘 RAM |
|---|---|---|
| 7B 妯″瀷 | 8GB | 16GB |
| 14B 妯″瀷 | 16GB | 32GB |
| 32B 妯″瀷 | 32GB | 64GB + GPU 24GB VRAM |
| Embedding | 4GB | 8GB |

## 8. 涓嶉噰鐢ㄧ殑鏂规鍙婂師鍥?

| 鏂规 | 涓嶉噰鐢ㄥ師鍥?|
|---|---|
| 鑷爺 Agent 妗嗘灦鏇夸唬 LangChain | 鐢ㄦ埛闇€瑕佺幇鎴愮殑 AI 鐢熸€侊紝涓嶆槸閫犺疆瀛?|
| PocketFlow 浣滀负缂栨帓鏍稿績 | 绀惧尯澶皬锛岀淮鎶ら闄?|
| Desktop 鍘熺敓搴旂敤 (Electron/Tauri) | Phase 6 涔嬪墠涓嶉渶瑕?GUI |
| 澶?Agent 妗嗘灦 (CrewAI/AutoGen) | 褰撳墠闃舵涓嶉渶瑕佸鏉傚崗浣?|
| Kubernetes | 涓汉鍗曟満鍦烘櫙锛岃繃搴﹂厤缃?|
| 鍏ㄨ嚜鐮?RAG (涓嶄緷璧?LlamaIndex) | 鍓嶆湡妫€绱㈤€昏緫绠€鍗曪紝鍙嚜鐮旓紱鍚庣画鍙紩鍏?LlamaIndex |

## 9. 鎶€鏈€夊瀷鍘熷垯

1. **鏈€灏戜緷璧栧師鍒?*锛氳兘灏戣涓€涓寘灏卞皯瑁呬竴涓?
2. **绀惧尯鎴愮啛浼樺厛**锛氫笉閫夊皬浼楁鏋讹紝闄ら潪鏈夊帇鍊掓€х悊鐢?
3. **寤惰繜鍐冲畾**锛氫笉鍒伴偅涓€姝ワ紝涓嶅喅瀹氭妧鏈粏鑺?
4. **鍙浛鎹?*锛氭瘡涓粍浠跺簲璇ユ湁澶囬€夋柟妗?

