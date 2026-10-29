# MobleKurly main + CCTV + PDF (merge)

## Source of truth
- Base: `mfc_main.zip`
- Imported: `mfc_cctv_connected.zip` CCTV module (`CctvReceiver.*`, `MjpegBuffer.h`), admin CCTV tab
- Imported: `mfc_pdf.zip` integrated settlement / PDF window (`SettlementIntegrated.cpp`)
- Other main C++ source modules (Database, DlgInventory, LoginDialog, PiTcpClient, App, ConveyorProtocol) copied byte-for-byte.

## UI
- Worker tab 1: existing work dashboard plus bottom `작업 결산` button opens compact settlement report.
- Admin tab 2: full-camera CCTV left, four existing placeholder report cards right, `전체 매출 결산 · PDF 저장` bottom button opens full settlement report.
- Existing four report cards stay placeholders, since the PDF source provided a separate **integrated settlement** PDF feature, not implementations for those four cards.
- Admin CCTV default: `[cctv]` port 8081; requires a separate video stream at `http://<pi>:8081/video_feed`. Existing inspection camera `[camera]` is untouched.
- Admin-only tab permission and logout preserved.

## Configuration
1. Preserve your existing `config.ini` DB/PI settings.
2. Add `[cctv]` block from `config.example.ini`.
3. Set the host/port/path to the **actual** Pi CCTV stream. MFC source does not create the Pi stream.
4. Visual Studio 2022 MFC x64 build; PDF exporter depends on the original PDF module's Windows print-to-PDF environment.

## Validation
Structural static validation and ZIP integrity checks performed. Windows/MFC compiler, camera server, MySQL, printer/PDF flow not available for end-to-end validation in this environment. Test both worker/admin flows on Windows.
