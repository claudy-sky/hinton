# Hinton for SASA

세종과학예술영재학교(SASA) 학생을 위한 **로컬·오프라인 AI 학습 도우미**.
Intel 루나 레이크 16GB 노트북에서 완전 동작하도록 설계된, ChatGPT·Claude·NotebookLM에
준하는 무료 데스크톱 앱. 비서는 자신을 **Hinton**(제프리 힌턴에서 따온 이름)으로 소개한다.

3개 모드 — **💬 Chat / 📓 Notebook / 💻 Code** — 를 하나의 3-pane 워크스페이스로 제공하며,
중첩 가능한 **Projects(폴더)** 로 대화를 정리하고 폴더별 컨텍스트·지침을 부여할 수 있다.

> 브랜드명만 Hinton 으로 바뀌었다. 디스크상의 프로젝트 디렉터리, `harness` 파이썬
> 패키지, `OPENLM_` 환경변수 접두사, 그리고 프런트엔드 JS 네임스페이스
> `window.OpenLM` 은 그대로 유지된다(사용자에게 보이는 텍스트만 Hinton).

---

## 지금 바로 실행 (모델 없이, 의존성 없이)

GGUF 가중치(~12GB)나 `pip install` 없이도 앱 전체를 띄워볼 수 있다 — 내장
**모의(mock) 모델**과 **브라우저 개발 서버**(둘 다 표준 라이브러리만 사용)를 쓴다.

```powershell
# 1) 렌더링 스택을 로컬로 내려받기 (최초 1회, 오프라인 보장)
python scripts\fetch_vendor.py

# 2) 모의 모델 + 브라우저로 실행
.\scripts\run.ps1 -Serve -Mock
#   또는:  $env:OPENLM_MOCK="1"; python -m harness.main --serve
```

→ 브라우저에서 **http://127.0.0.1:8090** 접속.
채팅에 `렌더 데모` 라고 입력하면 마크다운·LaTeX·코드·Mermaid·그래프 렌더링을 한 번에 확인할 수 있다.

---

## 기능

### 3개 모드 워크스페이스
- **Chat** — 일반 대화 + 도구 호출(웹/학술 검색, 딥리서치, 파일 생성, 퀴즈 등).
- **Notebook** — 자료(PDF/DOCX/XLSX/TXT/MD)를 추출·청킹·임베딩해 RAG 질의(NotebookLM 류).
- **Code** — Python(Pyodide)·JS/HTML(iframe)·C/C++(gcc) 인브라우저 실행 에디터.

### Projects (중첩 폴더)
- 대화를 **중첩 폴더**(`folders` 테이블, `parent_id` 자기참조)로 정리한다.
- 폴더 트리에서 생성/이름변경/삭제/이동(`move_folder`, 순환 이동은 거부)을 지원하며,
  폴더 삭제 시 하위 폴더·컨텍스트는 cascade 삭제되고 소속 대화는 미분류(folder_id=NULL)로 돌아간다.
- 사이드바에서 선택한 폴더는 **활성 프로젝트**(`window.OpenLM.state.activeFolderId`)가 되어,
  새로 만드는 Chat/Notebook/Code 대화에 자동으로 그 `folder_id` 가 부여된다(공유 프로젝트 컨텍스트).

### 폴더별 컨텍스트 + 폴더별 지침 (상속)
- 폴더마다 **컨텍스트 파일**을 첨부(`add_folder_context`)하면 PDF/DOCX/XLSX/TXT/MD 에서
  텍스트를 추출(notebook RAG 추출기 재사용)해 저장한다(최대 100,000자).
- 폴더마다 **지침(instructions)** 과 **톤(tone)** 을 설정(`set_folder_prefs`)할 수 있다.
- **상속**: 프롬프트에는 루트→리프 순서로 조상 폴더의 지침과 컨텍스트가 합쳐져 주입되며,
  합쳐진 컨텍스트는 약 8,000자로 잘린다(`prompts.folder_preamble`).

### 전역 사용자 환경설정 + 응답 톤
- 전역 **About me / Style / Tone** 을 `settings.json` 에 저장한다
  (`get_preferences` / `set_preferences`, 키: `pref_about`·`pref_style`·`pref_tone`).
- **Tone** 값(고정 enum): `default`, `friendly`, `formal`, `concise`, `detailed`,
  `socratic`, `encouraging`. 각 톤은 구체적 지시문으로 변환되어 시스템 프롬프트
  맨 앞(`prompts.preferences_preamble`)에 주입된다.

### 모드 간 연결 (Cross-view linking)
- **Open in Code** — Chat 의 어시스턴트 코드 블록을 Code 모드 에디터로 보낸다
  (`OpenLM.sendToCode(code, lang)`).
- **Discuss in Chat** — Code(현재 에디터)·Notebook(선택 텍스트/소스)의 내용을 Chat
  작성창에 채워 보낸다(`OpenLM.sendToChat(text)`).
- **공유 활성 프로젝트** — 위 활성 프로젝트(`activeFolderId`)가 세 모드에 걸쳐 공유된다.

### 라이트/다크 테마
- 라이트·다크 **테마 토글**을 제공한다.

### 그 외
- 마크다운·KaTeX·highlight.js·Mermaid·그래프 렌더링(전부 로컬 동봉).
- 퀴즈 + 오답 추적, 학습자료 생성(PPTX·DOCX·XLSX·PDF), 세션 간 메모리.

---

## 데스크톱 GUI + 실제 모델

```powershell
pip install -r requirements.txt          # 권장: Python 3.11 / 3.12
python scripts\download_models.py         # MTP 드래프터 + 임베딩 모델
# SYCL + MTP 지원 llama-server.exe 를 PATH 에 두거나 OPENLM_LLAMA_SERVER 로 지정
.\scripts\run.ps1                         # pywebview 네이티브 창
```

`llama-server` 가 없으면 자동으로 모의 모델로 동작한다(`config.MOCK_LLM`).
SYCL 빌드 플래그·MTP 빌드 요건은 기획서 §3.2 / §4.4 참고.

### 모델 프로필 / 가중치 환경변수
`harness/config.py` 는 프로필과 환경변수로 `llama-server` 인자 벡터를 구성한다.

| 환경변수 | 의미 |
|----------|------|
| `OPENLM_MODEL_PROFILE` | `gemma`(기본, 전체 튜닝된 Gemma QAT+MTP 인자) 또는 `generic`(임의 GGUF용 최소·이식 가능 인자) |
| `OPENLM_E4B_MODEL` | 상주 E4B 모델 소스 — HF repo id 또는 로컬 `.gguf` 경로 |
| `OPENLM_12B_MODEL` | 에스컬레이션 12B 모델 소스 — HF repo id 또는 로컬 `.gguf` 경로 |
| `OPENLM_E4B_DRAFT` / `OPENLM_12B_DRAFT` | (선택) MTP 드래프트 모델 경로 |
| `OPENLM_LLAMA_SERVER` | `llama-server.exe` 경로(미설정 시 PATH 에서 탐색) |
| `OPENLM_MODELS_DIR` / `OPENLM_DATA_DIR` / `OPENLM_DB_PATH` | 가중치 / 데이터 / SQLite 경로 재지정 |
| `OPENLM_E4B_PORT`(8082) / `OPENLM_12B_PORT`(8083) | 각 모델 서버 포트 |
| `OPENLM_THREADS` / `OPENLM_THREADS_BATCH` | CPU 스레드 수 |
| `OPENLM_MOCK` | `1`/`true` 면 모의 모델 강제 |
| `OPENLM_EMBED_MODEL` | 노트북 RAG 임베딩 모델 |

`llama-server` 바이너리는 `scripts\get_llama_server.py` 로 받을 수 있다.

---

## 데스크톱 패키징 (설치 프로그램)

PyInstaller(윈도 onedir, 콘솔 없음) + Inno Setup 으로 단일 설치 파일을 만든다.

```powershell
.\scripts\build_app.ps1                  # -Clean 으로 build\·dist\ 초기화
#   -> dist\Hinton\Hinton.exe (+ _internal\)
ISCC packaging\installer.iss             # -> packaging\Hinton-Setup.exe
```

| 산출물 | 경로 |
|--------|------|
| 실행 파일 | `dist\Hinton\Hinton.exe` |
| 설치 프로그램 | `packaging\Hinton-Setup.exe` |

설치 위치는 `C:\Program Files\Hinton`, 사용자 데이터는 `%LOCALAPPDATA%\OpenLM`
(env 접두사 유지) 에 저장된다. 자세한 내용은 [`packaging/PACKAGING.md`](packaging/PACKAGING.md) 참고.

---

## 구현 상태

| 영역 | 상태 |
|------|------|
| SQLite 영속성 (8 테이블, §21) | ✅ |
| Projects: 중첩 폴더 + 폴더별 컨텍스트/지침/톤 + 상속 | ✅ |
| 전역 환경설정(About/Style/Tone) + 프롬프트 주입 | ✅ |
| 모드 간 연결(Open in Code / Discuss in Chat / 공유 활성 프로젝트) | ✅ |
| 라이트/다크 테마 토글 | ✅ |
| ModelManager: E4B 상주·12B 에스컬레이션·뮤텍스·Idle TTL (§5,§6) | ✅ |
| 모델 프로필(gemma/generic) + 가중치 env(`OPENLM_MODEL_PROFILE`/`*_MODEL`) | ✅ |
| 모의 모델 (OpenAI 호환, 표준 라이브러리) | ✅ |
| 에이전트 루프 + 도구 스키마 검증 + /compact 압축 (§7) | ✅ |
| 에스컬레이션/디에스컬레이션 도구 가로채기 (§5.3–5.4) | ✅ |
| 3-pane 프런트엔드 셸 (채팅/노트북/코드) + 패널 리사이즈 | ✅ |
| 렌더링 스택: markdown-it·KaTeX·highlight.js·Mermaid·그래프 (로컬 동봉, §9) | ✅ |
| 웹/학술/딥리서치 도구 (§11–13) | ✅ (deps 필요) |
| 노트북 RAG: 추출·청킹·임베딩·코사인 검색 (§14) | ✅ (deps 선택) |
| 퀴즈 + 오답 추적 (§15) | ✅ |
| 학습자료 생성 PPTX·DOCX·XLSX·PDF (§16) | ✅ (deps 필요) |
| 코드 실행: Python(Pyodide)·JS/HTML(iframe)·C/C++(gcc) (§18) | ✅ |
| 세션 간 메모리 (§20) | ✅ (열람/편집/삭제 UI) |
| 이미지 생성 (SDXL Turbo, §17) | 🔌 플러그인 stub (manifest disabled) |
| 데스크톱 패키징 (PyInstaller + Inno Setup, §23) | ✅ |

> deps 미설치 시 해당 플러그인은 **조용히 비활성화**되고 앱은 정상 부팅된다.
> 도구가 호출되면 "이 기능은 X 설치가 필요합니다" 안내를 반환한다.

---

## 구조

```
openlm/                       (디스크 디렉터리명은 유지; 브랜드는 Hinton)
  harness/                 백엔드 (Python)
    config.py              경로·포트·SERVERS args·mock 판별·모델 프로필
    db.py                  SQLite 스키마 + CRUD (folders / folder_context 포함)
    model_manager.py       모델 수명주기·라우팅 (단일 적재 뮤텍스)
    mock_llm.py            개발용 OpenAI 호환 모의 서버
    llm_client.py          표준 라이브러리 OpenAI 호환 클라이언트
    agent_loop.py          도구 호출 루프 + 컨텍스트 압축
    prompts.py             모드별 시스템 프롬프트 + 메모리/환경설정/폴더 주입
    plugins.py             플러그인 로더 (deps 없으면 graceful skip)
    api.py                 pywebview JS 브리지 (폴더/환경설정 API 포함)
    server.py              정적+JSON-RPC 개발 서버 (브라우저 폴백)
    main.py                진입점
    tools/                 registry + research·notebook_rag·file_gen·code_exec
  frontend/                UI (pywebview/브라우저 공용, ES module 미사용; window.OpenLM)
    index.html  styles.css  app.js
    modes/{chat,notebook,code}.js
    components/{render,split_panels,editor,quiz,doc_viewer}.js
    vendor/                로컬 동봉 렌더링 라이브러리
  plugins/<name>/manifest.json     §19 플러그인 매니페스트
  packaging/  hinton.spec · installer.iss · PACKAGING.md
  scripts/    run.ps1 · build_app.ps1 · fetch_vendor.py · download_models.py
              · get_llama_server.py · smoke_backend.py
  design/                  Stitch가 생성한 UI 참조(HTML·스크린샷)
  models/ data/            가중치 / SQLite·생성물 (런타임)
```

## UI 디자인

UI는 **Stitch**(Gemini)로 디자인 시스템(딥 차콜 + 인디고/에메랄드/앰버,
Space Grotesk·Inter·JetBrains Mono)을 만들고 채팅/노트북 화면을 생성해 그 토큰을
`styles.css` 에 그대로 반영했다. 라이트/다크 테마 토글을 지원한다. 원본은 `design/` 에 있다.

## 개발 메모

- 백엔드 스모크 테스트: `OPENLM_MOCK=1 python scripts\smoke_backend.py`
- 프런트 문법 검사: `node --check frontend\**\*.js`
- 환경변수: `OPENLM_MOCK`, `OPENLM_MODEL_PROFILE`, `OPENLM_E4B_MODEL`,
  `OPENLM_12B_MODEL`, `OPENLM_MODELS_DIR`, `OPENLM_DATA_DIR`,
  `OPENLM_LLAMA_SERVER`, `OPENLM_E4B_PORT`, `OPENLM_12B_PORT`
- 데스크톱 패키징: [`packaging/PACKAGING.md`](packaging/PACKAGING.md)
