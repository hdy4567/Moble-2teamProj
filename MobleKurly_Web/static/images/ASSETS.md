# 모블 컬리 이미지 및 디자인 기록

## 2026-10-22 웹 아이콘 v7

- 기본 웹 아이콘의 흰색 MK·크기·투명 영역은 유지하고, 파란 배경만 관리자 아이콘의 대표색 `#0993F3` 계열로 맞췄습니다.
- 홈페이지는 `moble-kurly-shortcut-v7.ico`, 180·192·512px PNG 및 `static/site.webmanifest`를 사용합니다.
- 브라우저 탭, Apple 바로가기, 설치형 웹 바로가기, Windows 팀원용 바로가기에서 같은 기본 아이콘을 사용합니다.
- 관리자 아이콘은 톱니 배지가 있는 기존 v6를 유지하여 기본 홈페이지와 쉽게 구분합니다.
- 재현 도구: `tools/build_web_icons.cjs` (배경색만 기계적으로 조정하며 MK 글자와 알파 채널은 원본 기준으로 유지).

2026-10-20 폴더 정리: 현재 웹 로고·아이콘(v6)은 이 폴더에 유지했습니다. 사용하지 않는 v1~v5 로고는 프로젝트의 `백업/로고제작기록/이전로고/`로 옮겼습니다. 아래 과거 제작 경로는 당시 기록입니다.

2026-10-16 개편. 메인 및 상품 이미지는 내장 image_gen 도구와 imagegen 스킬로 새로 제작했습니다. 참고 사이트의 사진이나 로고를 복제하지 않았습니다.

- 현재 메인 배너: static/images/hero-produce.png (2172 × 724, 2026-10-19)
- 현재 상품 이미지 아틀라스: static/images/produce-atlas.png (1254 × 1254, 정확한 2 × 2 레이아웃, 2026-10-19)
- 이전 컬러 박스 이미지 hero-packages.png / packages-atlas.png는 기록·복구용으로 보존했으며 현재 구매 화면에서는 사용하지 않습니다.
- 파비콘: static/images/favicon.svg (프로젝트 자체 벡터)
- 폰트: static/fonts/PretendardVariable.woff2 (Pretendard 1.3.9, SIL Open Font License, OFL.txt 동봉)

## 참고한 화면

- https://www.kurly.com/main : 1080px 쇼핑 콘텐츠, 통합 검색, 명확한 상품 가격/담기 버튼, 정보 계층, Pretendard
- https://moble.kr/index.php : 블루/네이비, 골드 포인트, 시원한 여백과 브랜드 톤

## 최종 메인 이미지 프롬프트

Use case: product-mockup. Asset type: premium Korean e-commerce website hero background for MOBLE KURLY. Generate a sophisticated ultra-wide 3:1 landscape studio photograph/3D photoreal still life. Four pristine matte cardboard rectangular retail packages: warm coral red, saturated cobalt blue, buttery yellow, muted sage green, arranged at elegant staggered heights on pale blue minimal geometric platforms. Tiny elegant white typographic mark 'MOBLE KURLY' on each box, no other text. Main grouping concentrated in RIGHT 60 percent of frame; LEFT 40 percent is calm empty icy blue / off-white negative space for HTML headline. Soft blue architectural backdrop, subtle translucent glass arch far behind, understated tech precision but luxury editorial shopping campaign. Eye level/three-quarter angle, convincing paper textures, delicate shadows, large diffused window light from upper left, restrained palette, excellent art direction, not neon, not dark sci-fi, not cartoon. No people, no food, no web UI, no badges, no large text, no watermark. Wide photographic banner composition.

## 최종 상품 이미지 프롬프트

Use case: product-mockup. Asset type: one 2x2 product photography atlas sprite image for four e-commerce cards. The input is a STYLE AND PACKAGING REFERENCE ONLY. Create an exactly square 2048x2048 contact sheet split into FOUR PERFECTLY EQUAL square quadrants without any gap, border, lettering outside packages, or divider. Each quadrant is a complete isolated editorial studio product shot, precisely centered one matte premium MOBLE KURLY cardboard package in three-quarter perspective on subtle small plinth, camera and scale consistent, 20% negative space around product for CSS crop safety. TOP LEFT: coral RED package on blush ivory background. TOP RIGHT: cobalt BLUE package on icy pale blue background. BOTTOM LEFT: buttery YELLOW package on pale warm cream background. BOTTOM RIGHT: sage GREEN package on pale celadon background. Tiny white text MOBLE KURLY on packages only. Each package entirely contained within its own quadrant and not touching any quadrant edge. Sophisticated realistic paper texture and soft directional shadows like the reference image. This is one uniform 2x2 sprite atlas with exact equal quadrants to be displayed by CSS background-position 0% 0%, 100% 0%, 0% 100%, 100% 100%. No other objects, no extra packages, no food, no watermark.

메인 생성 이미지를 상품 이미지의 스타일 참조로 사용했습니다. 결과의 실제 해상도는 도구 출력 기준입니다.

## 2026-10-19 신선식품 이미지 변경

사용자 확정: RED 딸기, BLUE 블루베리, YELLOW 노랑 파프리카, GREEN 브로콜리. 내장 `image_gen` 도구와 `imagegen` 스킬의 기본 모드로 두 이미지를 새로 생성했습니다. 이전 이미지를 편집하거나 특정 판매처의 상품 사진을 복제하지 않았습니다. 실제 상품의 크기·중량·산지·품질을 보증하는 사진이 아니며 카드와 상세창에 연출 이미지라고 안내합니다.

- 프로젝트 최종 경로: `static/images/produce-atlas.png`, `static/images/hero-produce.png`
- 아틀라스 좌표: 좌상 딸기, 우상 블루베리, 좌하 노랑 파프리카 2개, 우하 브로콜리 1개.
- 내장 도구 원본은 Codex generated_images 폴더에 보존하고, 사용한 결과를 프로젝트로 복사했습니다. 작업별 임시 경로를 런타임에서 참조하지 않습니다.
- 음식·로고·인증·원산지 문구를 사진 안에 임의로 추가하지 않았습니다. 블루베리의 자연스러운 청보라색은 유지했습니다.

### 최종 생성 프롬프트: 상품 아틀라스

Use case: product-mockup. Asset type: one square 2x2 food photography atlas sprite for four Korean grocery product cards. Create exactly four perfectly equal square quadrants touching at exact vertical and horizontal center with NO border, gutter or divider. Each quadrant is a separate polished studio food photograph, eye-level three-quarter view, realistic fresh produce on subtle matching pale background, consistent scale and camera, soft natural side light, delicate shadows, premium restrained editorial art direction. TOP LEFT: a small clear unbranded produce punnet abundantly filled with vivid RED strawberries and green calyxes, a few loose strawberries beside it, pale blush ivory background. TOP RIGHT: a small clear unbranded punnet full of ripe blueberries with natural dusky BLUE-violet bloom, several loose blueberries nearby, pale ice-blue background. BOTTOM LEFT: exactly TWO whole glossy YELLOW bell peppers with green stems, one slightly ahead, pale buttery ivory background; no red or green bell pepper. BOTTOM RIGHT: exactly ONE fresh GREEN broccoli head, crown facing camera, on pale celadon ivory background. Center every subject group within its own square with at least 18 percent blank margins so a CSS crop does not cut it. All food is fresh, not frozen. No people, hands, text, labels, logos, country flags, organic certificates, watermarks, price tags, web interface, cartons or colored boxes. Whole output is exactly square and 2x2 layout is exact. Photographic realism, appetizing natural textures, not illustration.

### 최종 생성 프롬프트: 메인 배너

Use case: product-mockup. Asset type: ultra-wide 3:1 Korean grocery website hero background. Premium editorial still-life photograph for a blue-and-navy minimalist fresh-food market. Main food arrangement in the RIGHT 55 percent ONLY: a tasteful clear unbranded punnet of bright red strawberries, a small ceramic bowl of naturally dusky blue blueberries, exactly two glossy yellow bell peppers, and one fresh green broccoli head, arranged at varied subtle heights on pale icy-blue low platforms. Food is fresh, realistic and recognizable, delicate condensation only where natural, soft large-window lighting, refined editorial styling, calm pale ice-blue and off-white backdrop, slight shallow depth of field but all four product types readable. Leave the LEFT 45 percent almost empty pale icy blue for HTML headline overlay, no object crossing the left text area. Camera three-quarter eye level, elegant restrained spacious composition, food grouping framed fully inside right side with breathing room, avoid edge cropping. No people, hands, utensils, lettering, labels, logos, certificates, origin claims, text, watermark, shopping UI, colored cardboard packages or extra foods. Actual photographic food textures, professional Korean fresh grocery campaign, not cartoon or vector.
# 2026-10-19 supplied individual product photos

## 두 번째 기획전 배너

`static/images/hero-table.png` (2172 × 724)는 이전 작업에서 내장 image_gen으로 생성해 보관한 `hero-berries.png`를 편집 없이 재사용했습니다. 중단된 할인 기능은 복원하지 않았습니다. 화면 문구는 HTML로 분리했고 상품 연출 이미지임을 표시합니다.

생성 프롬프트: Use case: ads-marketing. Asset type: premium Korean grocery ecommerce wide hero photograph, 3:1 panoramic aspect. Photoreal editorial still life of plump red strawberries and dusty blue blueberries, white ceramic shallow bowls on softly lit pale powder blue and warm off-white linen surface. Berries and bowls in RIGHT HALF, left 55% completely uncluttered pale blue negative space for live Korean HTML headline. Elevated camera, appetizing natural textures. Restrained premium airy blue/navy palette with beige linen. No text, logos, packaging, watermark. One coherent wide banner.

## 팀원 제공 상품 사진

`static/images/products/*.webp` (12 images) were supplied in `MobleKurlyFlask_cart_with_photos.zip`. The accompanying PRODUCT_PHOTOS_README.md describes them as AI-generated staged product imagery. This merge preserves the supplied files without editing. Their original generation prompts were not supplied. Product-ID mapping is documented in 병합_내역_20261019.md; the files do not seed or change any database rows. On-page disclosure remains 상품 연출 이미지.
