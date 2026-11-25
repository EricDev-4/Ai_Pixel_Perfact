# pixel-sprite 사용법

GPT Image로 만든 픽셀아트를 **픽셀퍼펙트 게임 스프라이트**로 바꾸는 Claude Code 스킬
위치: `~/.claude/skills/pixel-sprite/`

#gamedev #pixelart #ai

---

## 0. 처음 한 번만
```
! brew install Hugo-Dz/tap/spritefusion-pixel-snapper
```
Pixel Snapper가 없으면 스킬이 실행되지 않습니다.

---

## 1. 역할 분담

| 누가 | 하는 일 |
|---|---|
| **나 (사용자)** | 캐릭터 컨셉·동작 설명, 이미지 생성 (Codex 연동 전까지), 최종 결정 |
| **Claude** | 프롬프트 작성, 생성된 이미지 검수, 스크립트 실행, 문제 프레임 찾기 |
| **GPT Image** | 캐릭터·방향·애니메이션 이미지 생성 |
| **sprite.py** | 스냅, 프레임 추출, 정렬, 배경 제거, 시트 패킹 |

## 2. 전체 흐름

```
① 레퍼런스 준비        Claude 자동
② 소스 캐릭터 생성     컨셉 → GPT Image
③ 앵커 만들기          Claude 자동 (스냅 → 1024 업스케일)
④ 방향 앵커            GPT Image → Claude 자동 스냅
⑤ 동작 시트 생성       GPT Image (동작마다 1장)
⑥ 후처리               Claude 자동 → sheet.png 완성
⑦ 검수·수정            Claude가 문제 프레임 찾음 → 그 프레임만 재생성
```

에셋 작업은 `D:\Ai_PixelArt\workspace\<종류>\<이름>`에서 진행한다. 픽셀퍼펙트 처리를 마치고 검사한 에셋당 최종 PNG 한 장만 `D:\Ai_PixelArt\workspace\PixelPerfact\<에셋명>.png`에 저장한다. 생성 원본·시안·검토본·프레임·미리보기는 작업 폴더에 보관한다. 애니메이션의 최종 PNG는 합쳐진 시트 한 장이며 `D:\Ai_PixelArt\workspace\PixelPerfact\sheet\<캐릭터>_<동작>_sheet.png`에 저장한다.

---

## 3. Claude에게 이렇게 말하면 됨

### 처음 시작
> 픽셀 스프라이트 만들자. 캐릭터는 **갈색 코트를 입은 젊은 해적, 빨간 두건, 한 손에 커틀러스**. 횡스크롤 게임이라 왼쪽 방향만 필요해. 동작은 idle, attack, hurt, walk.

이것만 말하면 Claude가 단계마다 **생성할 프롬프트 파일, 첨부할 이미지(순서 포함), 저장할 경로**를 알려줍니다.

### 컨셉 잘 쓰는 법
| 좋음 ✅ | 나쁨 ❌ |
|---|---|
| 외형 위주: 옷, 색, 머리, 무기 | 분위기·배경·조명 ("어두운 숲 속의…") |
| 색을 2~4개로 제한 | 디테일이 많은 장식, 문양 |
| 무기는 1개, 단순한 모양 | 여러 개의 소품 |
| **마젠타(#FF00FF 같은 진분홍) 옷·소품 금지** (배경 제거가 깨짐) | 마젠타 망토, 형광 분홍 눈 |

예시:
- "은색 갑옷을 입은 기사, 파란 망토, 긴 검, 투구 없음, 금발"
- "보라색 로브의 마법사 소녀, 큰 뾰족 모자, 나무 지팡이"
- "해골 전사, 녹슨 도끼, 찢어진 갈색 천"

### 동작 요청
> attack 8프레임 만들어줘. 칼을 위에서 아래로 크게 내려베는 느낌.

> idle은 숨 쉬는 느낌으로 10프레임, 망토만 살짝 흔들리게.

> death는 뒤로 쓰러지는 10프레임.

동작 설명은 한국어로 해도 됩니다. Claude가 영어 프롬프트로 바꿔서 넣습니다.

### 검수·수정 요청
> attack 결과 보여줘
> 3번이랑 7번 프레임 빼고 다시 만들어줘
> 5번 프레임 칼이 반대 손에 있어. 고쳐줘
> walk 2번이랑 3번 사이가 끊겨. 중간 프레임 하나 넣어줘
> 미리보기에서 캐릭터가 흔들려

---

## 4. 이미지 생성할 때 (수동, Codex 연동 전)

Claude가 알려주는 대로 ChatGPT(또는 Codex 앱)에서:

1. **레퍼런스 이미지를 순서대로 첨부** (프롬프트가 "Image 1, Image 2"로 부르니 순서가 중요)
2. 프롬프트 파일 내용을 그대로 붙여넣기 (Claude에게 "클립보드에 복사해줘"라고 하면 됨)
3. 설정
   - 한 장짜리(캐릭터, 방향, 수정): **정사각형 1024×1024**
   - 동작 시트: **가장 큰 가로형 사이즈**
   - **PNG**, **고품질**, 1장
4. 결과를 Claude가 말한 **정확한 경로**에 저장 → "저장했어"

생성 결과가 이상하면 (캐릭터가 바뀜, 방향 틀림, 배경이 마젠타 아님) Claude가 다시 생성하라고 알려줍니다.

---

## 5. 동작별 가이드

| 동작 | 프레임 | 설명 방식 | 정렬 |
|---|---|---|---|
| Idle | 10 | 프레임별로 구체적으로 | 발 |
| Attack | 8 | 흐름만 느슨하게 | 발 |
| Hurt | 6 | 둘 중 하나 | 발 |
| Death | 10 | 프레임별로 구체적으로 | 발 |
| Jump | 6 | 둘 중 하나 | 몸통 |
| Walk | 8 | 포즈 가이드 사용 | 몸통 |

한 방식이 잘 안 되면 다른 방식으로 바꿔서 다시 생성합니다.

### 구체적 방식 예시 (Idle)
```
- Frame 1: settled idle
- Frame 2: tiny breathing rise
- Frame 3: breathing rise
- Frame 4: breathing peak
- Frame 5: soft blink or cloth sway
- Frame 6: small breathing fall
- Frame 7: settling fall
- Frame 8: near neutral
- Frame 9: return to settled idle
- Frame 10: loop hold matching frame 1
```

### 느슨한 방식 예시 (Attack)
```
Motion guidance:
- Create 8 readable attack poses that feel like one coherent short game animation.
- Use a clear beginning, anticipation, active strike, follow-through, and recovery
  back toward the starting stance.
- Let the model choose the exact in-between poses; do not force a named pose into each frame.
- Keep the same attacking side, weapon hand, weapon silhouette, and facing direction.
- The first frame should read as ready/idle and the final frame should return to
  that same ready stance for looping.
```

---

## 6. 걷기 (Walk)

이미지 모델은 걷기의 **다리 순서**를 자주 틀립니다. 그래서 **막대인간 포즈 가이드**를 같이 넣습니다.
- 🔴 빨강 = 화면 쪽(가까운) 팔·다리, 🔵 파랑 = 먼 쪽 팔·다리
- 레퍼런스 3장: `[방향 앵커, 포즈보드, walkguide_8]`

**잘 안 되면 단계적으로:**
1. **8프레임 한 번에** (walkguide_8) → 다리 순서 확인
2. 틀리면 **키 포즈 4장만** (walkguide_4) → 4장을 다 맞춘 뒤 → 사이사이 **중간 프레임 4장**을 하나씩 생성해서 끼워 넣기 (4→1 사이 포함해야 루프가 자연스러움)
3. 그래도 안 되면 4프레임 걷기로 쓰거나 Aseprite에서 몇 픽셀 직접 수정

---

## 7. 자주 생기는 문제와 대처

| 증상 | Claude에게 | 내부 처리 |
|---|---|---|
| 프레임이 너무 많음 / 중복 | "N번, M번 빼줘" | `--pick` |
| 무기 든 손이 바뀜 | "N번 칼이 반대 손이야" | `fix` 프롬프트로 그 프레임만 재생성 → 교체 |
| 동작이 뚝 끊김 | "N번이랑 M번 사이 끊겨" | `inbetween` 프롬프트로 중간 프레임 생성 → 삽입 |
| 캐릭터가 덜덜 떨림 | "미리보기에서 흔들려" | 정렬 기준 변경 (`--anchor torso`) |
| 특정 프레임만 크기가 다름 | (Claude가 경고 보고) | 빼거나 재생성 |
| 프레임 수가 적게 추출됨 | (Claude가 보고) | 시트에서 캐릭터끼리 너무 붙어 있음 → 재생성 |
| 마젠타 찌꺼기 | 자동 제거 | despeckle |

수정한 프레임은 `raw/` 폴더에 들어가고, 거기서부터 시트를 다시 만듭니다. AI 원본 시트를 다시 추출해서 **수정분을 덮어쓰는 일은 막혀 있습니다.**

---

## 8. 결과물

```
sprites/pirate/
├── refs/                 체커, 포즈보드, 걷기 가이드
├── source.png            AI 원본 캐릭터
├── anchor.png            스냅된 기준 캐릭터 (1024)
├── anchor_west.png       왼쪽 방향 앵커
└── attack/
    ├── raw/              추출된 프레임 (수정·삽입은 여기에)
    ├── frames/           256×256 완성 프레임 (투명 배경)
    ├── sheet.png         최종 시트 → 게임에 넣는 파일
    └── preview.gif       재생 미리보기
```

- 기본 프레임 크기 256×256. 바꾸려면 "프레임 크기 128로 해줘"
- 여러 줄 배치: "5열로 해줘" (예: 10프레임 → 1280×512)
- 오른쪽 방향은 게임 엔진에서 좌우 반전

---

## 9. 알아둘 것
- **pixel_size**: AI 그림에서 도트 1칸이 몇 픽셀인지. 생성 격자로 고정합니다: 1024 단일 그림은 16, 2048x1536 포즈 보드는 8. 모델이 격자를 안 지키면 경고가 나오고 재생성합니다. 그림은 리사이즈하지 않으며, `sheet --compare <앵커 native 파일>`은 키 차이를 경고만 합니다.
- 프롬프트 템플릿은 영어 그대로 쓰는 게 결과가 안정적입니다. 한글 번역은 Bear의 "GPT 픽셀아트 픽셀퍼펙트 워크플로우" 노트에 있습니다.
- Codex를 구독하면 Claude가 생성까지 자동으로 시도합니다 (현재 codex-cli 0.166에서는 안 됐음 → 구독 후 재검증).
- 아직 실제 AI 이미지로 끝까지 돌려본 적은 없습니다. 첫 캐릭터에서 결과를 같이 확인하세요.
