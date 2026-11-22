# EDI Assistant — Hướng dẫn sử dụng

## 1. Giới thiệu và cảnh báo an toàn

EDI Assistant đọc tệp Excel packing list của nhà máy, lập kế hoạch lô hàng và tự động nhập thông tin ASN lên cổng **EDI Gateway** của Burlington trong một trình duyệt hiển thị trên màn hình. Ứng dụng nằm ở khay hệ thống và báo cho bạn khi cần chú ý.

**Quan trọng:**

- Công cụ **KHÔNG BAO GIỜ bấm "Submit ASN"**. Khi nhập xong, công cụ dừng lại, phát thông báo và âm thanh: *"Đã nhập xong, vui lòng kiểm tra và tự bấm Submit"*. Bạn kiểm tra trên trang web rồi **tự bấm Submit ASN**.
- Công cụ **không bao giờ nhập mật khẩu**. Bạn tự đăng nhập trong trình duyệt do công cụ mở.
- Cài đặt > Luồng xử lý có mục "Khi ngày giao đã qua" (`flow.past_date_policy`): "Tự dùng hôm nay" hoặc "Hỏi tôi".
- Nếu mở Inspector (Hiệu chỉnh), hãy đóng Inspector trước khi thoát ứng dụng.
- Công cụ không tự bấm "Validate Shipment" (trừ khi bạn bật trong Cài đặt), không xoá, không huỷ lô hàng.
- Khi mở trang chi tiết PO, cổng sẽ đánh dấu PO là "đã đọc" — đây là hành vi bình thường.
- **Chế độ tốc độ như người thật** bật mặc định (Cài đặt → Tốc độ): trễ ngẫu nhiên giữa các thao tác, gõ từng ký tự, nghỉ giữa các lô. Nếu trang trả về "Access Denied", "Too Many Requests", CAPTCHA hoặc liên tục đẩy về trang đăng nhập, công cụ dừng ngay và hỏi bạn (Tiếp tục sau khi bạn xử lý xong, hoặc Dừng).
- Ngôn ngữ giao diện (`ui.language`: `en` hoặc `vi`, mặc định `en`) đổi trong Cài đặt → Trang web; có hiệu lực sau khi khởi động lại. Bản hướng dẫn tiếng Anh: `README.md`.
- Quy trình "PO bị thay thế" (Replaced) không được tự động hoá: công cụ chỉ báo và chờ bạn xử lý thủ công.

## 2. Cài đặt

Yêu cầu: Windows 10/11 và **Microsoft Edge** (đã có sẵn trên Windows). Nếu máy không có Edge, ứng dụng sẽ đề nghị tải Chromium dự phòng (khoảng 150 MB, menu *Công cụ → Cài trình duyệt Chromium…*).

### Bản portable (khuyến nghị)

1. Giải nén `EDI-Assistant-portable-x.y.z.zip` vào một thư mục bất kỳ (Desktop, USB…). Thư mục phải cho phép ghi.
2. Chạy `EDI Assistant\EDI Assistant.exe`.
3. Toàn bộ dữ liệu nằm trong thư mục `EDI Assistant\data\` (nhờ tệp `portable.flag` cạnh tệp exe). Muốn chuyển sang máy khác, chép cả thư mục.

### Máy tính công ty (bị khoá cài đặt)

Nhiều máy công ty chặn việc cài phần mềm, vì vậy bản portable (zip) là cách dùng chính. Có hai tệp zip:

| Tệp zip | Nội dung | Dùng khi |
|---|---|---|
| `EDI-Assistant-portable-x.y.z.zip` (lite) | Chỉ ứng dụng; điều khiển Microsoft Edge | Máy có Edge và cho phép tự động hoá |
| `EDI-Assistant-portable-full-x.y.z.zip` (full) | Ứng dụng kèm Chromium riêng trong `browsers\` (nặng hơn ~150 MB) | **IT chặn tự động hoá Edge** (chính sách `RemoteDebuggingAllowed`) hoặc máy không có Edge; không cần tải gì khi chạy |

Các bước:

1. **Bỏ chặn tệp zip trước.** Chuột phải tệp `.zip` > *Properties* > tích **Unblock** > OK. (Nếu không, Windows gắn "Mark of the Web" cho mọi tệp giải nén và SmartScreen/antivirus có thể chặn tệp exe.)
2. **Giải nén vào thư mục có quyền ghi**, ví dụ Documents hoặc Desktop - không dùng `Program Files`. Dữ liệu nằm trong `data\` cạnh tệp exe.
3. Chạy `EDI Assistant\EDI Assistant.exe`. Lần đầu ứng dụng đề nghị **Kiểm tra hệ thống** (cũng có ở *Trợ giúp > Kiểm tra hệ thống...*): báo PASS / WARN / FAIL cho thư mục dữ liệu, việc mở trình duyệt (ẩn và hiện), Chromium đi kèm, Edge, truy cập `https://edi.coat.com/vms-gateway/login.do` (dùng proxy của hệ thống), khởi động cùng Windows và thông báo. Bấm **Sao chép báo cáo** rồi gửi cho IT hoặc bộ phận hỗ trợ.
4. Cài đặt > Trình duyệt: *Tự động* (mặc định) dùng Chromium đi kèm nếu có, nếu không thì Edge; nếu không mở được Edge (do chính sách hoặc chưa cài) sẽ chuyển sang Chromium nếu có, nếu không sẽ hiện thông báo gợi ý dùng bản full. Ứng dụng không tự tải trình duyệt khi chưa có xác nhận của bạn: chỉ tải sau khi bạn bấm *Công cụ > Cài trình duyệt Chromium...* hoặc trả lời Có ở câu hỏi lần chạy đầu.
5. Nếu chính sách chặn "Khởi động cùng Windows", ứng dụng cảnh báo nhẹ, tự bỏ tích tuỳ chọn và vẫn chạy bình thường.

**Nếu AppLocker hoặc antivirus chặn tệp exe**, hãy báo IT:

- Đường dẫn đầy đủ của tệp exe, ví dụ `C:\Users\<tên bạn>\Documents\EDI Assistant\EDI Assistant.exe` (và thư mục `EDI Assistant\` nếu cho phép theo đường dẫn).
- Mã băm SHA256 trong `SHA256SUMS.txt` (đi kèm các tệp zip; có cả mã của tệp exe). Có thể kiểm tra bằng `Get-FileHash "EDI Assistant.exe"`.
- Nhà phát hành/sản phẩm: SHYFT GLOBAL LLC / EDI Assistant (tệp exe chưa được ký số).
- Ứng dụng cần: HTTPS ra ngoài tới `edi.coat.com`; mở được trình duyệt do nó điều khiển (Edge có remote debugging, hoặc Chromium riêng trong `browsers\`).

### Bản cài đặt

1. Chạy `EDI-Assistant-Setup-x.y.z.exe` (không cần quyền quản trị, cài cho người dùng hiện tại).
2. Có thể chọn tạo biểu tượng ngoài màn hình và "Khởi động cùng Windows".
3. Dữ liệu nằm ở `%APPDATA%\EDI Assistant` (cấu hình, mẫu, nhà máy, kết quả) và `%LOCALAPPDATA%\EDI Assistant` (hồ sơ trình duyệt). Khi gỡ cài đặt, ứng dụng hỏi có xoá dữ liệu hay không; chọn "No" để giữ lại.

Chạy lần thứ hai khi ứng dụng đang mở sẽ chỉ đưa cửa sổ đang chạy lên phía trước.

## 3. Lần đầu sử dụng

1. **Lưu đăng nhập EDI một lần:** Cài đặt → **Đăng nhập EDI** → User ID + mật khẩu → **Lưu đăng nhập** (lưu trong Windows Credential Manager / macOS Keychain). Nếu chưa lưu, công cụ dừng ở trang đăng nhập để bạn tự đăng nhập.
2. Không còn bước "Mở trình duyệt" riêng: bấm **Bắt đầu nhập liệu** là công cụ tự mở trình duyệt (hồ sơ riêng của công cụ), tự đăng nhập và vào EDI Gateway. (Menu ở khay hệ thống vẫn có *Mở trình duyệt* khi cần xem trang bằng tay.)
3. Thêm nhà máy: bấm **Thêm/Sửa…** ở nhóm "Nhà máy". Nhập tên, địa chỉ, thành phố, quốc gia… (có thể đặt "Tên khác" để nhận dạng tự động). Ứng dụng gợi ý nhà máy từ tên công ty ở đầu/cuối tệp Excel.
   - **Nhập cả danh sách từ Excel (khuyên dùng):** bấm **Nhập từ Excel…** (hoặc *Tệp > Nhập danh sách nhà máy (Excel)…*) và chọn file `factories.xlsx` (sheet đầu tiên, mỗi dòng một nhà máy; cột Factory Name, Address 1, Address 2, City, State, Zip, Country, Aliases (cách nhau bằng `;`), Code, Transportation Method, SCAC Code). Chỉ cần nhập một lần; khi danh sách thay đổi thì nhập lại file đó - nhà máy trùng tên được cập nhật, nhà máy mới được thêm, nhà máy không có trong file vẫn giữ nguyên.
   - Transportation Method / SCAC Code để trống = dùng giá trị trong Cài đặt; điền cho nhà máy chở bằng xe tải (vd. Mexico: LTL + mã SCAC hãng xe).

Lưu ý: ô Quốc gia của cổng chỉ liệt kê trực tiếp US, CA, CN. Với nước khác, công cụ sẽ tạm dừng và nhờ bạn chọn thủ công.

## 4. Quy trình hằng ngày

1. **Chọn tệp Excel** (nút *Chọn tệp…* hoặc menu Tệp → Mở Excel).
2. **Kiểm tra ánh xạ cột.** Với bố cục mới, hộp thoại *Ánh xạ cột Excel* hiện ra: xem trước tiêu đề, kiểm tra cột gợi ý cho từng trường (xanh = tin cậy cao), sửa nếu sai. Giữ ô **"Ghi nhớ bố cục này"** để lần sau ứng dụng tự áp dụng. Bố cục đã học được nhận dạng tự động ("Đã nhận dạng mẫu: …"); bố cục gần giống sẽ được điền sẵn và cần bạn xác nhận.
3. **Chọn nhà máy** và tuỳ chọn: một lô cho cả tệp hoặc mỗi PO chính một lô; chạy thử; ghi ASN vào bản sao Excel (`<tên>_ASN.xlsx`, tệp gốc không bị sửa).
4. **Kiểm tra bảng kế hoạch.** Dòng đỏ có lỗi (ví dụ số lượng không chia hết cho số thùng) — nút Bắt đầu bị khoá cho tới khi sửa Excel/ánh xạ. Dòng vàng là cảnh báo.
5. Bấm **Bắt đầu nhập liệu**. Theo dõi danh sách bước; có thể thu nhỏ vào khay.
6. **Hộp thoại tạm dừng.** Khi cần bạn (đăng nhập, bước lỗi, ngày giao, số lượng lệch…), cửa sổ hiện ra kèm thông báo và âm thanh, có ảnh chụp trang và (nếu bật AI) giải thích bằng tiếng Việt:
   - **Tiếp tục** — bạn đã tự xử lý trên trang (hoặc đã nhập giá trị yêu cầu), công cụ kiểm tra lại rồi chạy tiếp.
   - **Bỏ qua bước** — bỏ bước này, làm tiếp.
   - **Dừng** — kết thúc lần chạy; trình duyệt giữ nguyên.
7. **Nhận thông báo hoàn tất.** Kiểm tra kỹ dữ liệu trên trang rồi **tự bấm Submit ASN**.
8. Kết quả: tab *Lịch sử* và tệp `results.csv` trong thư mục `runs\<mã lần chạy>`.

## 4a. Tệp PO tracker

Tệp **PO tracker** MDDP (các cột `Master PO #`, `Line #`, `ASN #`, `Order Units`, `EDI PO Start/End Ship`, `Pack`, `Gross Weight/Carton(kg)`) được nhận dạng tự động; hộp thoại ánh xạ hiện **Định dạng tệp: PO tracker** và cho phép đổi sang *Packing list* khi cần.

- **Ô chọn trong bảng kế hoạch.** Mỗi dòng PO có một ô chọn; chọn/bỏ chọn một dòng sẽ áp dụng cho mọi dòng của cùng PO chính. Dòng đã có ASN ở cột `ASN #` mặc định bị bỏ chọn và hiện màu xám ("đã có ASN ..."). Dòng đỏ (lỗi) khoá nút **Bắt đầu** cho tới khi bạn sửa Excel hoặc bỏ chọn dòng đó. Các dòng cùng một lô (PO chính) có cùng màu nền.
- **Mỗi PO chính một lô** (tuỳ chọn gom nhóm bị cố định). Ngày giao lấy từ cột Excel `EDI PO Start/End Ship` (điểm giữa của phần giao nhau); ngày trên trang PO chỉ để đối chiếu.
- **Số thùng.** SL/thùng = `Pack`, số thùng = `Order Units / Pack` (phải là số nguyên). Công cụ so với *Qty Ordered* trên web: bằng Order Units -> Pack mỗi thùng; bằng Order Units / Pack (prepack) -> 1 mỗi thùng; khác -> dừng chờ bạn. Trọng lượng mỗi dòng PO = `Gross Weight/Carton(kg)` đúng như trong tệp (đổi tại Cài đặt > Quy trình > *Trọng lượng cho tệp PO tracker*).
- **Nhà máy tự chọn theo cột Factory Name.** Tracker xuất từ PO PDF (`PO_EXTRACT_TRACKER_FORMAT`) có cột *Factory Name*: ứng dụng tự chọn nhà máy khớp trong danh sách; nếu chưa có thì báo để bạn nhập danh sách/thêm mới. Khi cột *Order Units* trống, số lượng lấy từ cột *EDI Units*.
- **Chế độ nhanh** (Settings → Workflow, mặc định bật): header, PO, carton, Partial và cân nặng được gửi thẳng như form của trình duyệt (cùng phiên đăng nhập) - một shipment 10 PO mất dưới 1 phút thay vì vài phút. Có gì bất thường thì chạy tiếp trên trình duyệt từ đúng trang đó. Không bao giờ gửi Validate Shipment / Submit ASN.
- **Lưu đăng nhập** (Settings → Đăng nhập EDI): lưu trong Windows Credential Manager / macOS Keychain, không nằm trong file hay log; công cụ tự đăng nhập ở trang đăng nhập EDI (thử một lần).
- **TO Site No tự chọn theo cột Delivery Address.** Lấy bang ở cuối địa chỉ (`..., ELLABELL, GA 31308` → GA → 934) theo thông báo của EDI: CA=512, NJ=053, GA=934. Sửa bảng này trong Settings → *TO Site No theo bang*. Nếu địa chỉ không có bang, hoặc các dòng của một shipment đi về các DC khác nhau, bản xem trước sẽ báo và khi chạy ứng dụng sẽ dừng để bạn chọn site trong trình duyệt.
- **Nhà máy theo từng lần chạy.** Tracker không có cột nhà máy (và tên file không bắt đầu bằng *Code* của nhà máy): hãy chọn nhà máy gửi hàng mỗi lần chạy (nhà máy lần trước được chọn sẵn và được nhớ khi bấm Bắt đầu).
- **Bản sao ghi ASN.** Sau mỗi lô, Web Shipment ID được ghi vào cột `ASN #` của bản sao `<tên>_ASN_<YYYYMMDD-HHMMSS>.xlsx` cạnh tệp gốc (hoặc trong thư mục lần chạy nếu thư mục gốc không ghi được). Tệp gốc và cột `Submit ASN # (w/ Date)` không bao giờ bị sửa; chạy thử không ghi gì. Hãy dán số ASN vào tracker chính sau khi bạn Submit.
- **Kiểm tra giữa các lô.** Cài đặt > Quy trình > *Tạm dừng để kiểm tra giữa các lô* điều khiển việc dừng sau khi mỗi lô được nhập xong.

## 5. Chạy thử và chế độ mock

- **Chạy thử** (tuỳ chọn *Chạy thử*): công cụ đi đến ngay trước nút Save của lô hàng rồi dừng, không lưu gì trên cổng. Nên dùng cho lần đầu với trang thật.
- **Chế độ mock** (tập dượt không cần mạng): chạy `EDI Assistant.exe --mock` — ứng dụng tự mở một cổng EDI giả lập cục bộ. Hoặc bật "Dùng trang giả lập" trong Cài đặt và chạy riêng `python -m edi_assistant.mock_edi --port 8765`.
- Các tham số dòng lệnh khác: `--minimized` (khởi động vào khay), `--data-dir ĐƯỜNG_DẪN` (đổi nơi lưu dữ liệu).

## 6. Hiệu chỉnh bộ chọn (Calibrate / Learn)

Khi trang web đổi giao diện hoặc công cụ không tìm thấy một nút/ô nhập, dùng *Công cụ → Hiệu chỉnh bộ chọn…*:

1. Mở trình duyệt và đi tới đúng trang (nút nhanh: Inbox, New Shipment, Drafts).
2. Chọn một khoá trong danh sách (khoá chưa xác minh ✗ được xếp lên đầu). Nếu khoá cần PO/Site No, điền vào ô "Biến thay thế".
3. **Tô sáng** để xem công cụ đang chọn phần tử nào; **Kiểm tra** để xem kết quả tìm.
4. Nếu sai hoặc không thấy: bấm **Chọn trên trang**, rồi bấm vào đúng phần tử trong trình duyệt (Esc để huỷ). Bộ chọn mới được lưu và dùng ưu tiên từ lần sau.
5. **Xoá đã học** để quay về bộ chọn mặc định. **Mở Inspector** mở Playwright Inspector cho người dùng nâng cao.

## 7. Cấu hình AI (tuỳ chọn) và chi phí

Công cụ hoạt động đầy đủ khi **tắt AI**. Khi bật, AI chỉ được gọi lúc có sự cố: đề xuất bộ chọn mới, giải thích lỗi bằng tiếng Việt, hoặc đọc ngày giao từ ảnh. Số lần gọi tối đa mỗi lần chạy mặc định là 8 (rất rẻ — thường vài cent mỗi ngày).

*Công cụ → Cài đặt… → AI:*

1. Chọn **mẫu nhà cung cấp**: Anthropic (Claude Haiku — rẻ, hoặc Claude Sonnet), OpenAI, Google Gemini, DeepSeek, Qwen, OpenRouter, Ollama (chạy trên máy, không cần key).
2. Dán **API key**, bấm **Kiểm tra kết nối**.
3. Tích "Bật trợ lý AI". Có thể tắt "Gửi ảnh chụp màn hình" nếu model không hỗ trợ ảnh hoặc muốn giảm dữ liệu gửi đi.

Lưu ý bảo mật: API key lưu dạng văn bản thường trong `config.yaml` của thư mục dữ liệu; mật khẩu và e-mail trên trang được che trước khi gửi cho AI. Không dùng AI nếu chính sách công ty không cho phép gửi ảnh chụp trang.

## 8. Vị trí dữ liệu và nhật ký

| Nội dung | Portable | Bản cài đặt |
|---|---|---|
| Cấu hình `config.yaml`, mẫu `templates\`, nhà máy `factories.json`, bộ chọn đã học `selectors.learned.yaml` | `data\` cạnh tệp exe | `%APPDATA%\EDI Assistant` |
| Hồ sơ trình duyệt, Chromium dự phòng | `data\` | `%LOCALAPPDATA%\EDI Assistant` |
| Nhật ký `logs\edi_assistant.log` | `data\logs` | `%APPDATA%\EDI Assistant\logs` |
| Kết quả `runs\<mã>\results.csv`, `run.json` | `data\runs` | `%APPDATA%\EDI Assistant\runs` |

Menu *Công cụ → Mở thư mục dữ liệu* mở thẳng thư mục này. `results.csv` mở được bằng Excel.

## 9. Khắc phục sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Không mở được trình duyệt | Cài Microsoft Edge, hoặc *Công cụ → Cài trình duyệt Chromium…* rồi đổi "Trình duyệt" trong Cài đặt. |
| Dừng ở "Cần đăng nhập" | Đăng nhập trong cửa sổ trình duyệt của công cụ rồi bấm *Tiếp tục*. |
| "Không tìm thấy phần tử …" | Làm bước đó bằng tay trên trang rồi *Tiếp tục*; hoặc hiệu chỉnh bộ chọn (mục 6). |
| Nút *Bắt đầu* bị khoá | Có dòng đỏ trong bảng, chưa chọn nhà máy, hoặc chưa xác nhận ánh xạ cột. |
| Số lượng không chia hết cho số thùng | Kiểm tra lại cột Số lượng / Số thùng trong Excel và ánh xạ. |
| Không đọc được ngày giao | Nhập ngày thủ công trong hộp thoại, hoặc bật AI vision. |
| PO hiện "Replaced" | Thực hiện quy trình thay thế PO thủ công trên cổng, rồi *Tiếp tục*. |
| Không có thông báo/âm thanh | Bật trong Cài đặt → Thông báo; kiểm tra "Không làm phiền" của Windows. |
| Thư mục portable không ghi được | Chép sang thư mục có quyền ghi; ứng dụng sẽ dùng `%APPDATA%` nếu không ghi được `data\`. |
| Lỗi khác | Gửi tệp `logs\edi_assistant.log` và ảnh chụp hộp thoại cho người hỗ trợ. |
