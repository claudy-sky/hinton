# Hinton

**로컬·오프라인 AI 학습 도우미 데스크톱 앱.** 인터넷 없이 내 노트북에서만 도는
무료 학습 비서로, 실제 **Gemma 4** 모델을 GPU 가속으로 구동한다. 비서는 자신을
**Hinton**(제프리 힌턴에서 따온 이름)으로 소개한다. Intel 루나 레이크 16GB 노트북을
기준으로 설계했으나, GPU 백엔드는 Intel·AMD·NVIDIA에서 모두 동작한다.

Chat / Notebook / Code 세 모드를 하나의 워크스페이스로 제공하고, 중첩 가능한
**Projects(폴더)** 로 대화를 정리하며 폴더별 컨텍스트·지침을 부여할 수 있다.

> **리네임 규칙**: 사용자에게 보이는 텍스트만 Hinton이다. 디스크 디렉터리명
> `openlm`, 파이썬 패키지 `harness`, 환경변수 접두사 `OPENLM_`, 프런트엔드 JS
> 네임스페이스 `window.OpenLM`, 사용자 데이터 폴더 `%LOCALAPPDATA%\OpenLM` 은
> 그대로 유지된다.

데이터는 전부 로컬에 남는다. 어떤 대화도 기기를 떠나지 않는다.

---

## 어떻게 동작하나

- **데스크톱 셸**: `hinton-tauri/` (Tauri 2 + Rust). 네이티브 WebView2 창이
  파이썬 백엔드(`python -m harness.main --serve`)를 **사이드카**로 띄우고 그 로컬
  URL을 로드한다. 프런트엔드와 백엔드는 그대로 재사용된다.
- **백엔드**: `harness/` (순수 파이썬). SQLite 영속성, 모델 수명주기·라우팅,
  에이전트 루프, 도구, 시스템 프롬프트.
- **추론 엔진**: 동봉한 **Vulkan 빌드 `llama-server`** (OpenAI 호환). 가중치 없이도
  표준 라이브러리 모의(mock) 서버로 전체 UI를 띄울 수 있다.

### 비서의 성격 (시스템 프롬프트)

Hinton의 행동 원칙은 Anthropic의 *Claude's Constitution(2026)* 을 압축·각색한
것이다: **진짜 도움**(과한 회피 금지), **정직**(거짓말·아첨 금지, 불확실성은 솔직히),
**인식 자율성 존중**, **해악 회피**, 그리고 넘지 않는 **하드 제약**(대량살상무기·CSAM
등). 응답 스타일은 **이모지 금지·빈말 오프너 금지**로 고정되어 있다.

---

## 빠른 실행

### 1) 모델·의존성 없이 (모의 모델)

```powershell
python scripts\fetch_vendor.py            # 렌더링 라이브러리 로컬 동봉 (최초 1회)
$env:OPENLM_MOCK="1"; python -m harness.main --serve
```
→ 브라우저에서 **http://127.0.0.1:8090** 접속. 채팅에 `렌더 데모` 입력 시
마크다운·LaTeX·코드·Mermaid·그래프 렌더링을 한 번에 확인할 수 있다.

### 2) 실제 Gemma 4 (개발 실행)

```powershell
# 모델·바이너리 받기 (최초 1회)
python scripts\get_gemma.py --size e4b            # 상주 모델 (~5GB)
python scripts\get_gemma.py --size g4-12b         # (선택) 12B 에스컬레이션 (~7GB)
python scripts\get_llama_server.py                # Vulkan llama-server.exe + ggml-vulkan.dll

python -m harness.main --serve                    # 실제 모델로 실행
```
`generic` 프로파일이 기본이며, `models/` 에 있는 GGUF와 동봉 `bin/llama-server.exe`
를 자동으로 찾는다. `llama-server` 가 없으면 자동으로 모의 모델로 폴백한다.

### 3) 데스크톱 앱 (Tauri)

```powershell
cd hinton-tauri\src-tauri
cargo build --release          # -> target\release\hinton.exe
```
`hinton.exe` 를 실행하면 네이티브 창이 뜨고 백엔드·모델이 자동 기동된다. 자세한
빌드/설치는 [`packaging/PACKAGING.md`](packaging/PACKAGING.md) 참고.

---

## 모델과 추론

| 모델 | 역할 | 크기(q4) | 배치 | 속도(검증, Arc 130V) |
|------|------|----------|------|----------------------|
| **Gemma 4 E4B** | 상주(기본) | ~5GB | 8GB GPU에 전부 적재 | ~24 tok/s |
| **Gemma 4 12B** | 에스컬레이션(선택) | ~7GB | GPU+CPU 하이브리드 | ~12 tok/s |

- **교차 벤더 GPU**: 동봉 `llama-server` 는 **Vulkan** 빌드라 Intel·AMD·NVIDIA에서
  단일 바이너리로 가속된다(`ggml-vulkan.dll`).
- **메모리 자동 분배(`OPENLM_NGL=auto`, 기본)**: GPU(약 8GB)에 들어갈 만큼 레이어를
  얹고 나머지는 시스템 RAM으로 보내, 루나레이크의 **16GB 통합 메모리**를 전부 쓴다.
  E4B는 전부 GPU에, 12B는 GPU+CPU로 자동 분할된다.
- **KV 캐시 양자화**: `-fa on --cache-type-k q8_0 --cache-type-v q4_0` 로 KV 캐시를
  f16 대비 ~3/8로 줄여 컨텍스트 여유를 확보한다.
- **첫 응답 워밍업**: 모델 로드 직후 1토큰을 미리 생성해 Vulkan 셰이더 컴파일
  지연을 사용자 첫 메시지에서 떼어낸다.

**의도적으로 끈 것**
- **NPU**: llama.cpp에 NPU 백엔드가 없어 사용하지 않는다(OpenVINO는 인텔 전용이라
  교차 벤더와 상충).
- **MTP draft(추측 디코딩)**: Gemma 4 MTP 어시스턴트는 `gemma4_mtp` 아키텍처라
  메인라인 Vulkan 빌드가 로드하지 못한다(인텔 SYCL+MTP 포크 전용). E2B를 일반
  draft로 쓰면 8GB GPU를 초과하고 2B→4B 비율이라 실익이 없어, draft는 끈다.

### 환경변수

| 변수 | 의미 |
|------|------|
| `OPENLM_MODEL_PROFILE` | `generic`(기본·유일 지원) / `gemma`(레거시, SYCL+MTP 빌드 전용) |
| `OPENLM_E4B_MODEL` / `OPENLM_12B_MODEL` | 모델 소스 — HF repo id 또는 로컬 `.gguf` 경로 |
| `OPENLM_LLAMA_SERVER` | `llama-server.exe` 경로(미설정 시 동봉 `bin/` → PATH 탐색) |
| `OPENLM_NGL` | GPU 오프로드. `auto`(기본, GPU+CPU 자동분배) / 정수(레이어 고정, `0`=순 CPU) |
| `OPENLM_FLASH_ATTN` | `on`(기본) / `off` / `auto` |
| `OPENLM_CACHE_TYPE_K` / `_V` | KV 캐시 타입(기본 `q8_0` / `q4_0`; V는 flash attention 켜졌을 때만 적용) |
| `OPENLM_THREADS` / `_BATCH` | CPU 스레드 수(기본=전체 논리 코어) |
| `OPENLM_MODELS_DIR` / `OPENLM_DATA_DIR` / `OPENLM_DB_PATH` | 가중치 / 데이터 / SQLite 경로 |
| `OPENLM_E4B_PORT`(8082) / `OPENLM_12B_PORT`(8083) | 모델 서버 포트(점유 시 자동 회피) |
| `OPENLM_MOCK` | `1`/`true` 면 모의 모델 강제 |
| `OPENLM_EMBED_MODEL` | 노트북 RAG 임베딩 모델 |

---

## 기능

### 3개 모드 워크스페이스
- **Chat** — 일반 대화 + 도구 호출(웹/학술 검색, 딥리서치, 파일 생성, 퀴즈 등).
- **Notebook** — 자료(PDF/DOCX/XLSX/TXT/MD)를 추출·청킹·임베딩해 출처 인용 RAG 질의.
- **Code** — Python(Pyodide)·JS/HTML(iframe)·C/C++(gcc) 인브라우저 실행 에디터.

### Projects (중첩 폴더) + 상속
- 대화를 **중첩 폴더**(`folders.parent_id` 자기참조)로 정리. 생성/이름변경/삭제/이동
  (순환 이동 거부), 삭제 시 하위·컨텍스트 cascade, 소속 대화는 미분류로 복귀.
- 폴더별 **컨텍스트 파일**(추출 텍스트, 최대 100,000자)과 **지침·톤**을 부여하면
  루트→리프 순으로 조상 폴더까지 합쳐 프롬프트에 주입된다(합산 ~8,000자로 절단).
- 사이드바에서 고른 폴더는 **활성 프로젝트**가 되어 새 대화에 자동 적용된다.

### 전역 환경설정 + 응답 톤
- 전역 **About / Style / Tone** 을 저장(`settings.json`). 톤 enum: `default`,
  `friendly`, `formal`, `concise`, `detailed`, `socratic`, `encouraging`.

### 실시간 생성 표시
- 응답 중 **"Thinking… / Generating… N tokens · E4B"** 처럼 단계와 토큰 수가
  실시간 갱신된다. 응답 **중단 버튼**도 제공한다.

### 모드 간 연결
- **Open in Code**(채팅 코드블록 → 에디터), **Discuss in Chat**(에디터/노트북 →
  채팅 입력창), 세 모드가 공유하는 **활성 프로젝트**.

### 그 외
- 라이트/다크 테마, 마크다운·KaTeX·highlight.js·Mermaid·그래프(전부 로컬 동봉),
  퀴즈+오답 추적, 학습자료 생성(PPTX·DOCX·XLSX·PDF), 세션 간 메모리.

> 선택 의존성(torch/weasyprint 등)이 없으면 해당 플러그인은 **조용히 비활성화**되고
> 앱은 정상 부팅된다. 도구 호출 시 "이 기능은 X 설치가 필요합니다"를 안내한다.
> 이미지 생성(SDXL)은 현재 비활성 stub.

---

## 구조

```
openlm/                       (디스크 디렉터리명은 유지; 브랜드는 Hinton)
  harness/                 백엔드 (Python)
    config.py              경로·포트·SERVERS args·프로파일·GPU/KV 설정
    db.py                  SQLite 스키마 + CRUD (folders / folder_context 포함)
    model_manager.py       모델 수명주기·라우팅 (단일 적재 뮤텍스·워밍업·포트 회피)
    llm_client.py          표준 라이브러리 OpenAI 호환 클라이언트 (SSE 스트림·토큰 콜백)
    agent_loop.py          도구 호출 루프 + 컨텍스트 압축 + 진행 이벤트
    api.py                 JS 브리지 + get_progress 스냅샷 (폴더/환경설정 API)
    server.py              정적 + JSON-RPC 개발 서버(브라우저/사이드카 공용)
    prompts.py             시스템 프롬프트(헌법 각색) + 메모리/환경설정/폴더 주입
    mock_llm.py            개발용 OpenAI 호환 모의 서버
    plugins.py  main.py    플러그인 로더 / 진입점
    tools/                 registry + research·notebook_rag·file_gen·code_exec
  frontend/                UI (사이드카/브라우저 공용, ES module 미사용; window.OpenLM)
    index.html  styles.css  app.js
    modes/{chat,notebook,code}.js
    components/{render,split_panels,editor,quiz,doc_viewer}.js
    vendor/                로컬 동봉 렌더링 라이브러리
  hinton-tauri/            Tauri 2 데스크톱 셸 (Rust) — 네이티브 창 + 파이썬 사이드카
  bin/                     동봉 Vulkan llama-server.exe + ggml-vulkan.dll (런타임)
  models/ data/            가중치 / SQLite·생성물 (런타임, git 제외)
  scripts/                 get_gemma.py · get_llama_server.py · fetch_vendor.py
                           · run.ps1 · smoke_backend.py · verify_hinton.py
  packaging/               PACKAGING.md (Tauri 빌드 문서)
  design/                  Stitch가 생성한 UI 참조
```

---

## 개발 메모

- 백엔드 스모크 테스트: `OPENLM_MOCK=1 python scripts\smoke_backend.py`
- 프런트 문법 검사: `node --check frontend\**\*.js`
- 권장 파이썬: 3.11 / 3.12 (torch/weasyprint 휠 공백으로 3.14는 일부 플러그인 제외)
- UI는 **Stitch**(Gemini)로 디자인 시스템(딥 차콜 + 인디고/에메랄드/앰버,
  Space Grotesk·Inter·JetBrains Mono)을 만들어 `styles.css` 에 반영. 원본은 `design/`.
