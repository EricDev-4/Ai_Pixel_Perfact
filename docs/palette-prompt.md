# 팔레트 규칙 (색 문법) — 최종 검토본

상태: **사용자 승인 2026-11-17**. 규칙은 `AGENTS.md`(CLAUDE.md가 import)에 반영. 공용 팔레트는 ENDESGA 32(`project/palettes/endesga-32.hex`). 프롬프트 템플릿·`sprite.py` 반영은 아직.
작성: Claude + Codex 토론 결과, 2026-11-17.

## 원칙

목표는 **색 일관성**이다. 팔레트는 그 수단이다.

1. **재질에 맞는 색이 최우선.** 팔레트 안에서 그 재질에 가장 어울리는 색을 고른다. '전체 팔레트에서 가장 가까운 색'이 재질을 깨면(예: 화분 속 짙은 갈색 → 잎 그림자 초록) 그 매핑은 쓰지 않는다.
2. **팔레트 안 색을 최대한 유지.** 팔레트 밖 색은 일관성을 깨므로 최대한 피한다. 단, 절대 금지는 아니다.
3. **팔레트 밖 색은 막지 않고 보고한다.** 승인 전에는 '미승인 예외'로 표시하고 최종본으로 보지 않는다.

## 색 문법 7개 (수정본)

1. **기본 팔레트** 목업 화면 1장 기준 16~32색(Lospec 등 공개 팔레트 사용 가능). 팔레트는 버전 있는 파일로 고정한다. 새 스테이지·재질은 램프 단위로 추가.
2. **램프** 색은 재질별 램프(어둠→밝음)로 묶는다. 정리는 AI, 승인은 사용자.
3. **생성** 색 이름 + 팔레트 스와치 보드 + 승인된 색 레퍼런스를 함께 준다. hex 코드만 믿지 않는다. 프롬프트는 유도일 뿐 준수를 보장하지 않는다.
4. **후처리** 매번 같은 순서: 배경 정리 → 팔레트로 다시 칠하기 → 검사.
5. **다시 칠하기** 재질을 먼저 구분하고, 같은 재질 램프 안에서 밝기 순서대로 매핑한다. '가장 가까운 색'은 재질이 확정된 픽셀 안에서 보조로만 쓴다.
6. **검사** 캐릭터는 불투명 색 최대 16색(외곽선·무기·하이라이트 포함, 투명 제외). 팔레트 밖 색은 위치·색값·픽셀 수와 함께 보고. 재질이 애매한 픽셀은 표시.
7. **예외 색** 대비가 부족하거나 팔레트로 재질을 표현할 수 없을 때만 추가한다. 색마다 대상·색 이름·hex·이유를 적고 하나씩 승인받는다(한 번에 여러 색 가능, 색별 승인). 승인되면 장면 팔레트와 캐릭터 팔레트를 함께 버전 올려 편입하고 전체를 다시 검사한다. 예외 색도 캐릭터 16색 상한에 포함된다.

## 준비물

- **장면 팔레트 파일:** 예) `project/palettes/scene_v1.hex`. 색 이름·재질·램프 순서를 함께 기록.
- **캐릭터 팔레트:** 장면 팔레트의 부분집합 ≤16색. 예) `project/palettes/<character>_v1.hex`. 부분집합인지 검증한다.
- **크로마키 충돌 검사:** 승인 색이 `#FF00FF` 배경 판정(`is_key`)과 번짐 제거(despill)에 걸리지 않는지 승인 전에 확인한다.
- **색 레퍼런스:** 승인된 목업 화면, 또는 승인된 색·재질 레퍼런스 이미지. 첫 소스 생성에는 승인 앵커가 없으므로 이것을 쓴다.
- **포즈 가이드의 빨강·파랑·체커 색은 팔레트 근거가 아니다.**

## 이미지 생성용 블록 (영어, 기존 템플릿 끝에 추가)

배경 지시는 기존 템플릿(`#FF00FF`) 것을 그대로 쓴다. 레퍼런스 번호는 실제 첨부 순서에 맞춘다.

```text
Color palette (follow closely):
Image {PALETTE_REF_INDEX} is the approved palette swatch board. Each row is one
named material ramp, ordered darkest to lightest. Do not draw the swatch board.
Image {COLOR_REF_INDEX} is the approved color reference. Match its material
color placement and shading steps.
Pose-guide colors (red, blue, checker) are not output colors.

Material ramps, darkest -> lightest:
{MATERIAL}: {COLOR_NAME_1} ({HEX_1}) -> {COLOR_NAME_2} ({HEX_2}) -> {COLOR_NAME_3} ({HEX_3}) -> {COLOR_NAME_4} ({HEX_4})
{REPEAT_FOR_EACH_MATERIAL}

Rules:
- Use only colors from these ramps. At most 16 distinct colors on the character,
  including outline, weapon and highlights.
- Shade by stepping along the SAME material's ramp. Never shade one material
  with another material's color.
- Solid, hard-edged pixel clusters. No gradients, anti-aliasing, blur, glow,
  semi-transparent edges, color noise or soft lighting.
- Pure black or white only if listed in a ramp.
- Keep identical colors on the same material in every frame.
- The chroma-key background color is not part of the palette; never use it or
  its spill on the character.
```

## 후처리·검사 지시 (작업 에이전트용)

```text
1. 배경 정리: 크로마키와 번짐을 제거한다. 번짐 픽셀은 그 자리 재질의 램프 색으로 복원한다.
   재질이 불명확한 번짐 픽셀은 표시한다. 모든 번짐을 외곽선 색 하나로 덮지 않는다.
   재질 색이 키 판정에 걸리면 재질 색을 바꾸지 말고 판정 기준을 조정하고 보고한다.
2. 다시 칠하기: 재질 마스크(기본) 또는 사용자 승인 색→재질 대응표(보조)로 재질을 구분한다.
   같은 재질 램프 안에서 밝기 순서를 보존해 매핑한다. 밝기 기준과 임계값은 시퀀스 전체에 고정한다.
   전체 팔레트 대상 최근접 매핑, 색 개수만 줄이는 양자화로 대체하지 않는다.
   재질이 애매한 픽셀은 표시하고 검토본으로 출력한다.
3. 검사: 저장한 파일을 다시 열어 집계한다. 완전 투명 픽셀은 제외한다.
   - 팔레트 밖 색(기준: 해당 캐릭터 팔레트): 색값·픽셀 수·위치·이유 보고. 승인 전에는 '미승인 예외'.
   - 캐릭터 불투명 색 수 ≤16.
   - 반투명 픽셀 수(0이어야 함).
   - 애니메이션: 프레임별 색 집합과 전체 합집합. 같은 재질이 프레임마다 같은 색인지.
   - 대상: frames/*.png, sheet.png. preview.gif는 납품 대상일 때 따로 검사.
4. 결과 기록: 팔레트 버전, 색 수, 팔레트 밖 색 목록, 애매 픽셀 수, 반투명 수, PASS/검토 필요.
   검사를 실행하지 않았으면 통과라고 보고하지 않는다.
```

## 출력 형식

- 최종본(팔레트 밖 색 없음 또는 전부 승인됨)은 캐릭터 팔레트를 담은 인덱스 PNG(8비트, 투명 1칸). 엔진이 RGBA를 요구하면 그대로 풀어 쓴다(새 색 없음).
- 검토본(미승인 예외 색·애매 픽셀 있음)은 RGBA PNG로 저장하고 파일명에 `_review`를 붙인다. 승인 팔레트만 담은 인덱스 PNG로는 미승인 색을 표현할 수 없기 때문이다.
- 인덱스 PNG여도 저장 후 검사는 한다.
- 엔진 설정: 텍스처 필터 Point, 압축·밉맵 끔. 파일 색이 맞아도 화면 색은 달라질 수 있다.
- 손 수정: Aseprite Indexed 모드에 캐릭터 팔레트를 불러와 칠하고, 저장 후 다시 검사한다.

## 적용 시 필요한 sprite.py 변경 (승인 후 구현)

| 순서 | 변경 | 위치 |
|---|---|---|
| 1 | `check` 명령 추가: 팔레트 밖 색, 색 수, 반투명, 프레임 합집합 보고 | 새 명령 |
| 2 | snapper 색 처리 결정: `--palette`로 캐릭터 팔레트를 먼저 강제하면 재질 구분에 필요한 색 차이가 사라질 수 있음. 내부 매핑을 확인한 뒤, 강제할지 또는 색 수를 넉넉히 두고 5번 재칠에 맡길지 결정 | `run_snapper` `sprite.py:75` |
| 3 | `cmd_put`의 `Image.LANCZOS` → `Image.NEAREST` | `sprite.py:364` |
| 4 | despill이 초록 재질을 외곽선 색으로 덮는 문제 수정. 번짐은 그 자리 재질 색으로 복원, 불명확하면 표시 | `clean` `sprite.py:226` |
| 5 | 재질 인식 재칠하기 (마스크 또는 대응표) | 새 명령 |

## 미확인

- snapper `--palette`의 내부 매핑 방식. 최근접일 가능성이 높아 재질 인식 재칠(5번)이 여전히 필요할 수 있다.
- 인덱스 투명 PNG의 엔진별 실제 임포트 결과.
- 영상의 "hex 정확도 10% 미만"(GenColorBench, CVPR 2026) 원 논문.
- 실제 이미지로 검증한 적 없음. 승인된 팔레트도 아직 없음.
