# 옆모습 1방향 제작 계획

기준일 2026-11-19. 동작 생성은 PixelLab(2026-11-19 Pixel Engine에서 변경)입니다.

## 1. 방식

- 캐릭터는 **왼쪽(west)을 보는 옆모습 한 방향**만 만듭니다. 오른쪽은 게임 엔진에서 좌우 반전합니다.
- 화면이 탑다운이어도 캐릭터는 좌우로만 바라봅니다. 위·아래로 이동할 때는 마지막에 바라본 좌우 방향 스프라이트를 그대로 씁니다.
- 앵커(정지 이미지)는 GPT Image(Codex)로 1장 만들고, 동작은 PixelLab이 그 앵커를 그대로 움직여 만듭니다.
- 탑다운 4방향(S, W, N + E 반전)보다 동작당 생성 횟수가 1/3입니다.

## 2. 캐릭터 종류별 애니메이션 구성

idle은 `sprite.py idle`로 앵커에서 만들어 **비용이 들지 않습니다.**

| 동작 | 프레임 | 반복 | 비고 |
|---|---|---|---|
| idle | 8 | 루프 | 무료 (앵커에서 생성) |
| walk | 8 | 루프 | |
| run | 8 | 루프 | |
| attack | 8 | 1회 | 빠른 동작은 중간 프레임 보정 필요할 수 있음 |
| skill | 8–10 | 1회 | 특수 공격 |
| hurt | 6 | 1회 | |
| death | 10 | 1회 | 누운 자세는 키 비교에서 제외 |

| 종류 | 포함 동작 | 유료 생성 동작 수 |
|---|---|---|
| **주인공** | idle, walk, run, attack, skill, hurt, death | 6 |
| **일반 몬스터 / 동료** | idle, walk, attack, hurt, death | 4 |
| **잡몹** | idle, walk, hurt | 2 |
| **NPC** | idle, walk | 1 |

## 3. PixelLab 비용

- 가격은 생성 시간에 따라 달라지는 추정치입니다. 작업마다 `sprite.py animate`가 실제 비용(`usage`)을 출력합니다.
- 참고(2026-11-19 가격표): `animate-with-text-v3` 128×128 16프레임 약 $0.042, `animate-pixminimax` 64×64 8프레임 약 $0.023.
- 플랜별 생성량은 실제 비용을 몇 번 기록한 뒤 다시 계산합니다.

## 4. 그 밖의 비용

- 앵커 생성은 PixelLab이 아니라 GPT Image(Codex, ChatGPT 구독)를 씁니다. 캐릭터당 1장, 재생성 1회까지.
- 공격 등의 중간 프레임 보정도 GPT Image로 합니다(`inbetween`).
- Claude는 프롬프트 작성, 검수, 후처리에 씁니다.

## 출처

- https://www.pixellab.ai/pixellab-api (가격)
- https://api.pixellab.ai/v2/openapi.json (엔드포인트, 크기 제한)
