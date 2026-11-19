"""All Vietnamese UI strings (module-level constants)."""

APP_TITLE = "EDI Assistant"
ABOUT_TEXT = ("{name} {version}\n\nCông cụ hỗ trợ nhập ASN trên EDI Gateway.\n"
              "Công cụ KHÔNG BAO GIỜ bấm Submit ASN — bạn kiểm tra và tự bấm Submit.")

# --- buttons
BTN_START = "Bắt đầu nhập liệu"
BTN_ABORT = "Dừng"
BTN_CONTINUE = "Tiếp tục"
BTN_SKIP = "Bỏ qua bước"
BTN_REVIEWED = "Đã hiểu"
BTN_CANCEL = "Huỷ"
BTN_CHOOSE = "Chọn"
BTN_CHOOSE_FILE = "Chọn tệp…"
BTN_EDIT_MAPPING = "Sửa ánh xạ cột…"
BTN_EDIT_FACTORY = "Thêm/Sửa…"
BTN_OPEN_BROWSER = "Mở trình duyệt"
BTN_OPEN_FOLDER = "Mở thư mục"
BTN_OPEN_CSV = "Mở CSV"
BTN_NEW = "Thêm mới"
BTN_SAVE = "Lưu"
BTN_DELETE = "Xoá"
BTN_TEST_CONNECTION = "Kiểm tra kết nối"

# --- main window
TAB_MAIN = "Nhập liệu"
TAB_LOG = "Nhật ký"
TAB_HISTORY = "Lịch sử"
GRP_EXCEL = "Tệp Excel"
GRP_FACTORY = "Nhà máy (địa chỉ gửi)"
GRP_OPTIONS = "Tuỳ chọn"
LBL_SHEET = "Trang tính:"
LBL_FACTORY_HINT = "Gợi ý từ tệp: {text}"
FACTORY_NONE = "(chọn nhà máy)"
OPT_PER_FILE = "Một lô cho cả tệp"
OPT_PER_MASTER_PO = "Mỗi PO chính một lô"
OPT_DRY_RUN = "Chạy thử (không lưu)"
OPT_WRITE_BACK = "Ghi ASN vào bản sao Excel"
STATUS_NO_FILE = "Chưa chọn tệp"
STATUS_NO_HEADER = "Không tìm thấy dòng tiêu đề"
STATUS_TEMPLATE_EXACT = "Đã nhận dạng mẫu: {name}"
STATUS_TEMPLATE_SIMILAR = "Mẫu gần giống: {name} — vui lòng kiểm tra"
STATUS_TEMPLATE_NEW = "Mẫu mới — vui lòng kiểm tra ánh xạ cột"
STATUS_MAPPING_CONFIRMED = "Đã xác nhận ánh xạ cột"
DLG_CHOOSE_EXCEL = "Chọn tệp Excel packing list"
FILTER_EXCEL = "Excel (*.xlsx *.xlsm);;Tất cả (*)"
PLAN_COLUMNS = ("", "Lô", "PO dòng", "PO chính", "Dòng", "Container", "Model #", "Mô tả", "Thùng",
                "SL/thùng", "SL đặt hàng", "Trọng lượng (KG)", "Ngày giao", "Trạng thái", "Cảnh báo")
HISTORY_COLUMNS = ("Mã lần chạy", "Bắt đầu", "Trạng thái", "Số lô", "Web Shipment ID")
LOG_LEVEL = "Mức nhật ký:"
LOG_WRITEBACK = "Đã ghi ASN vào: {path}"
LOG_WRITEBACK_FAIL = "Không ghi được ASN vào Excel: {err}"

# --- menus
MENU_FILE = "Tệp"
MENU_OPEN_EXCEL = "Mở Excel"
MENU_EXIT = "Thoát"
MENU_TOOLS = "Công cụ"
MENU_SETTINGS = "Cài đặt…"
MENU_CALIBRATE = "Hiệu chỉnh bộ chọn…"
MENU_INSPECTOR = "Mở Playwright Inspector"
MENU_INSTALL_CHROMIUM = "Cài trình duyệt Chromium…"
MENU_OPEN_DATA = "Mở thư mục dữ liệu"
MENU_HELP = "Trợ giúp"
MENU_GUIDE = "Hướng dẫn"
MENU_ABOUT = "Giới thiệu"

# --- tray / notifications
TRAY_TOOLTIP = "EDI Assistant đang chạy"
TRAY_SHOW = "Hiện cửa sổ"
TRAY_OPEN_BROWSER = "Mở trình duyệt"
TRAY_QUIT = "Thoát"
NOTIFY_FILLED_DONE = "Đã nhập xong, vui lòng kiểm tra và tự bấm Submit"
NOTIFY_NEEDS_USER = "Cần bạn xử lý"
NOTIFY_RUN_DONE = "Hoàn tất: {n} lô, Web Shipment ID: {ids}. Hãy kiểm tra và bấm Submit ASN thủ công."
NOTIFY_DRY_RUN_DONE = "Chạy thử đã xong (không lưu gì trên cổng)."
NOTIFY_RUN_ABORTED = "Đã dừng theo yêu cầu."
NOTIFY_RUN_FAILED = "Lần chạy thất bại: {err}"
CONFIRM_QUIT_RUNNING = "Đang có lần nhập liệu chạy. Thoát bây giờ sẽ dừng lại. Bạn chắc chắn muốn thoát?"

# --- errors
ERR_NO_SHEETS = "Tệp Excel không có trang tính nào."
ERR_NO_FACTORY = "Vui lòng chọn nhà máy (địa chỉ gửi) trước khi bắt đầu."
ERR_GUIDE_MISSING = "Không tìm thấy tệp hướng dẫn README_VI.md."

# --- browser install
ASK_INSTALL_CHROMIUM = ("Không tìm thấy Microsoft Edge hoặc Chromium. Tải Chromium dự phòng (~150 MB) bây giờ?")
INSTALL_CHROMIUM_TITLE = "Cài Chromium"
INSTALL_CHROMIUM_PROGRESS = "Đang tải Chromium (~150 MB)…"
INSTALL_CHROMIUM_OK = "Đã cài xong Chromium."
INSTALL_CHROMIUM_FAIL = "Cài Chromium không thành công. Xem tab Nhật ký hoặc thử lại."

# --- mapping dialog
MAPPING_TITLE = "Ánh xạ cột Excel"
MAPPING_HINT = "Chọn cột Excel tương ứng cho từng trường (* là bắt buộc)."
MAPPING_COL_FIELD = "Trường"
MAPPING_COL_COLUMN = "Cột Excel"
MAPPING_COL_CONF = "Độ tin cậy"
MAPPING_UNUSED = "(không dùng)"
MAPPING_PREVIEW = "Xem trước tiêu đề và 5 dòng dữ liệu đầu"
MAPPING_TEMPLATE_NAME = "Tên mẫu:"
MAPPING_REMEMBER = "Ghi nhớ bố cục này cho lần sau"
MAPPING_MISSING = "Còn thiếu trường bắt buộc: {fields}"
FIELD_LABELS = {
    "po": "Số PO", "line": "Số dòng", "description": "Mô tả", "packages": "Số thùng",
    "quantity": "Số lượng", "gross_weight": "Trọng lượng cả bì (G.W.)", "net_weight": "Trọng lượng tịnh (N.W.)",
    "size": "Kích thước",
    "asn": "ASN #", "model_no": "Model #", "start_ship": "EDI PO Start Ship", "end_ship": "EDI PO End Ship",
    "pack": "Pack (số lượng mỗi thùng)", "gw_per_carton": "Trọng lượng cả bì mỗi thùng (kg)", "container": "Container",
    "edi_units": "EDI Units (dùng khi Order Units trống)", "factory": "Tên nhà máy",
}

# --- factory dialog
FACTORY_TITLE = "Danh sách nhà máy"
FACTORY_NAME = "Tên"
FACTORY_ADDR1 = "Địa chỉ 1"
FACTORY_ADDR2 = "Địa chỉ 2"
FACTORY_CITY = "Thành phố"
FACTORY_STATE = "Tỉnh/Bang"
FACTORY_ZIP = "Mã bưu điện"
FACTORY_COUNTRY = "Quốc gia"
FACTORY_SITE_NO = "Site No"
FACTORY_ALIASES = "Tên khác (cách nhau bằng dấu phẩy)"
FACTORY_NEED_NAME = "Vui lòng nhập tên và địa chỉ 1."
FACTORY_CONFIRM_DELETE = "Xoá nhà máy này?"

# --- pause dialog
PAUSE_TITLE_DEFAULT = "Cần bạn xử lý"
PAUSE_TITLE = {
    "login_required": "Cần đăng nhập",
    "finished_review": "Đã nhập xong",
    "dry_run_stop": "Dừng chạy thử",
    "step_failed": "Bước bị lỗi",
    "po_replaced": "PO đã bị thay thế",
    "qty_mismatch": "Số lượng không khớp",
    "non_integer_carton": "Số thùng không chia hết",
    "dates_needed": "Cần nhập ngày giao",
    "no_date_intersection": "Khoảng ngày không giao nhau",
    "country_not_in_list": "Quốc gia không có trong danh sách",
    "unverified_selector": "Phần tử chưa được xác minh",
    "confirm": "Xác nhận",
    "site_blocked": "Trang web có thể đang chặn",
    "shipment_failed": "Lô bị lỗi",
    "date_in_past": "Ngày giao đã qua",
}
PAUSE_AI_EXPLANATION = "Giải thích của AI"
PAUSE_OPEN_SCREENSHOT = "Bấm để mở ảnh đầy đủ"

# --- settings dialog
SETTINGS_TITLE = "Cài đặt"
TAB_SITE = "Trang web"
TAB_BROWSER = "Trình duyệt"
TAB_FLOW = "Quy trình"
TAB_AI = "AI"
TAB_NOTIFY = "Thông báo"
TAB_PACE = "Tốc độ"
SET_BASE_URL = "Địa chỉ EDI Gateway"
SET_USE_MOCK = "Dùng trang giả lập (mock) để tập dượt"
SET_MOCK_URL = "Địa chỉ trang giả lập"
SET_VENDOR = "Tên hồ sơ nhà cung cấp"
SET_CHANNEL = "Trình duyệt"
SET_HEADLESS = "Chạy ẩn (không hiện cửa sổ trình duyệt)"
SET_SLOW_MO = "Làm chậm mỗi thao tác (ms)"
SET_TIMEOUT = "Thời gian chờ mặc định (ms)"
SET_GROUPING = "Cách chia lô"
SET_DRY_RUN = "Chạy thử (không lưu gì trên cổng)"
SET_WEIGHT_MODE = "Cách nhập trọng lượng"
SET_WEIGHT_TOTAL = "Tổng trọng lượng cả bì của dòng"
SET_WEIGHT_PER_CARTON = "Trọng lượng mỗi thùng (tổng / số thùng)"
SET_WEIGHT_HELP = "Chỉ áp dụng cho packing list. Mặc định là tổng G.W. của dòng PO. Chọn 'mỗi thùng' nếu cổng yêu cầu trọng lượng từng thùng."
SET_SHIPPING_TYPE = "Shipping Type"
SET_TRANSPORT = "Transportation Method"
SET_SCAC = "Mã SCAC"
SET_BOL = "Bill of Lading"
SET_PRO = "PRO Number"
SET_PACK_CODE = "Packaging Code (thùng)"
SET_COMPLETE_PARTIAL = "Complete / Partial"
SET_WEIGHT_UM = "Đơn vị trọng lượng"
SET_CLICK_VALIDATE = "Bấm 'Validate Shipment' sau khi nhập (không khuyến nghị)"
SET_CLICK_VALIDATE_HELP = "Công cụ không bao giờ bấm Submit ASN, kể cả khi bật tuỳ chọn này."
SET_WRITE_BACK = "Ghi ASN vào bản sao Excel"
SET_PAUSE_QTY = "Tạm dừng khi số lượng Excel khác số lượng đặt hàng"
SET_PAST_DATE = "Khi ngày giao đã qua"
SET_PAST_DATE_CLAMP = "Tự dùng hôm nay"
SET_PAST_DATE_ASK = "Hỏi tôi"
SET_AI_ENABLED = "Bật trợ lý AI (tuỳ chọn, tính phí theo nhà cung cấp)"
SET_AI_PRESET = "Mẫu nhà cung cấp"
SET_AI_PROVIDER = "Kiểu API"
SET_AI_BASE_URL = "Base URL"
SET_AI_KEY = "API key"
SET_AI_MODEL = "Model"
SET_AI_VISION = "Gửi ảnh chụp màn hình cho AI (vision)"
SET_AI_MAX_CALLS = "Số lần gọi AI tối đa mỗi lần chạy"
PRESET_LABELS = {
    "custom": "(tuỳ chỉnh)", "anthropic": "Anthropic — Claude Haiku", "anthropic_sonnet": "Anthropic — Claude Sonnet",
    "openai": "OpenAI", "gemini": "Google Gemini", "deepseek": "DeepSeek", "qwen": "Qwen (Alibaba)",
    "openrouter": "OpenRouter", "ollama": "Ollama (máy local)",
}
TEST_RUNNING = "Đang kiểm tra…"
TEST_NO_KEY = "Thiếu API key (hoặc chưa chọn nhà cung cấp)."
TEST_OK = "Kết nối thành công. Phản hồi: {text}"
TEST_BAD_REPLY = "Kết nối được nhưng phản hồi không đúng định dạng — thử model khác."
TEST_FAIL = "Kết nối thất bại: {text}"
SET_SOUND = "Phát âm thanh khi cần chú ý / khi hoàn tất"
SET_BALLOON = "Hiện thông báo ở khay hệ thống"
SET_START_MIN = "Khởi động thu nhỏ vào khay"
SET_START_WIN = "Khởi động cùng Windows"

# --- calibrate dialog
CALIB_TITLE = "Hiệu chỉnh bộ chọn"
CALIB_COLUMNS = ("Khoá", "Trang", "Đã xác minh", "Đã học", "Mô tả")
CALIB_ALL_PAGES = "(tất cả)"
CALIB_PAGE_FILTER = "Lọc theo trang:"
CALIB_VARS = "Biến thay thế"
CALIB_VAR_PO = "PO (9 chữ số)"
CALIB_VAR_SITE = "Site No"
CALIB_VAR_ROWKEY = "Row key"
CALIB_HIGHLIGHT = "Tô sáng"
CALIB_PICK = "Chọn trên trang"
CALIB_CANCEL_PICK = "Huỷ chọn"
CALIB_TEST = "Kiểm tra"
CALIB_FORGET = "Xoá đã học"
CALIB_INSPECTOR = "Mở Inspector"
CALIB_LINK_INBOX = "Hộp thư (Inbox)"
CALIB_LINK_NEW_SHIPMENT = "Lô hàng mới (New Shipment)"
CALIB_LINK_DRAFTS = "Bản nháp (Drafts)"
CALIB_OPEN_PAGE = "Mở trang:"
CALIB_WAITING = "Đang chờ bạn bấm vào phần tử…"
CALIB_CANCELLED = "Đã huỷ chọn."
CALIB_SAVED = "Đã lưu bộ chọn cho {key}."

# --- AI errors / test
AI_ERR_NETWORK = "Không kết nối được tới dịch vụ AI."
AI_ERR_HTTP = "Dịch vụ AI trả lỗi (HTTP {status})."
TEST_STEP_TITLE = "Kiểm tra kết nối"

# --- settings: language + human pace
SET_LANGUAGE = "Ngôn ngữ giao diện"
SET_LANGUAGE_HELP = "Có hiệu lực sau khi khởi động lại ứng dụng."
LANGUAGE_LABELS = {"en": "English", "vi": "Tiếng Việt"}
GRP_PACE = "Tốc độ như người thật (chống bị chặn, tăng độ ổn định)"
SET_PACE_ENABLED = "Bật chế độ tốc độ như người thật"
SET_PACE_HELP = "Thêm độ trễ ngẫu nhiên giữa các thao tác, gõ từng ký tự và nghỉ giữa các lô để trang web ít nghi ngờ hơn."
SET_PACE_ACTION = "Độ trễ giữa các thao tác (ms)"
SET_PACE_NAV = "Độ trễ thêm sau mỗi lần tải trang (ms)"
SET_PACE_TYPE = "Độ trễ mỗi ký tự khi gõ (ms)"
SET_PACE_MAX_HOUR = "Số lô tối đa mỗi giờ (0 = không giới hạn)"
SET_PACE_BETWEEN = "Nghỉ giữa các lô (giây)"
PACE_MIN = "từ"
PACE_MAX = "đến"

# --- PO-tracker (v2)
MAPPING_PROFILE = "Định dạng tệp:"
PROFILE_LABELS = {"po_tracker": "PO tracker", "packing_list": "Packing list"}
STATUS_PROFILE = "Định dạng: {profile}"
PLAN_STATUS_HAS_ASN = "đã có ASN {asn}"
PLAN_STATUS_UNSELECTED = "không chọn"
OPT_GROUPING_FORCED = "Tệp PO tracker luôn tạo mỗi PO chính một lô"
LBL_FACTORY_PICK_RUN = "Tệp này không có cột nhà máy - hãy chọn nhà máy gửi hàng cho lần chạy này"
ERR_NO_SELECTION = "Chưa chọn dòng PO nào."
SET_TRACKER_WEIGHT = "Trọng lượng cho tệp PO tracker"
SET_WEIGHT_PER_CARTON_AS_IS = "Trọng lượng cả bì mỗi thùng, như trong tệp"
SET_REVIEW_BETWEEN = "Tạm dừng để kiểm tra giữa các lô"
NOTIFY_SHIPMENT_DONE = "Đã tạo lô {idx}: Web Shipment ID {wid} (đã ghi vào {path})"

# --- locked-down PCs: system check, autostart, browser
MENU_SYSTEM_CHECK = "Kiểm tra hệ thống…"
SET_CHANNEL_AUTO = "Tự động (Chromium đi kèm, nếu không có thì Edge)"
SYSCHECK_TITLE = "Kiểm tra hệ thống"
SYSCHECK_RUNNING = "Đang kiểm tra máy tính… (mất vài giây)"
SYSCHECK_COPY = "Sao chép báo cáo"
SYSCHECK_COPIED = "Đã sao chép báo cáo vào bộ nhớ tạm."
SYSCHECK_CLOSE = "Đóng"
SYSCHECK_SUMMARY = "{n_pass} đạt, {n_warn} cảnh báo, {n_fail} lỗi"
SYSCHECK_REPORT_HEADER = "EDI Assistant {version} - kiểm tra hệ thống"
ASK_SYSTEM_CHECK_FIRST_RUN = ("Chạy kiểm tra hệ thống nhanh bây giờ? Việc này kiểm tra máy có cho phép trình duyệt, "
                              "truy cập mạng và các tính năng khác mà ứng dụng cần hay không.")
CHK_DATA_DIR = "Thư mục dữ liệu có ghi được"
CHK_BROWSER_HEADLESS = "Mở trình duyệt (chạy ẩn)"
CHK_BROWSER_HEADED = "Mở trình duyệt (có cửa sổ)"
CHK_BUNDLED = "Chromium đi kèm (bản full)"
CHK_EDGE = "Đã cài Microsoft Edge"
CHK_PORTAL = "Truy cập được cổng EDI"
CHK_AUTOSTART = "Khởi động cùng Windows (registry)"
CHK_NOTIFY = "Thông báo khay hệ thống"
CHK_OK_FOUND = "có"
CHK_NOT_FOUND = "không có"
CHK_SKIPPED = "không áp dụng trên hệ thống này"
CHK_HINT_NO_BROWSER = ("Không có trình duyệt dùng được. Hãy dùng bản zip portable 'full' (có sẵn Chromium) hoặc nhờ IT "
                       "cho phép Edge remote debugging (chính sách RemoteDebuggingAllowed).")
CHK_HINT_PORTAL = "Kiểm tra mạng/proxy hoặc nhờ IT cho phép https://edi.coat.com."
AUTOSTART_BLOCKED = ("Windows chặn cài đặt 'khởi động cùng Windows' (có thể do chính sách công ty). "
                     "Tuỳ chọn đã được tắt; ứng dụng vẫn hoạt động bình thường.")
BROWSER_LOCKED_DOWN = ("Không mở được trình duyệt. Chính sách công ty có thể chặn tự động hoá Microsoft Edge. "
                       "Hãy dùng bản zip portable 'full' hoặc chạy Trợ giúp > Kiểm tra hệ thống.")

# --- nhập danh sách nhà máy (Excel)
BTN_IMPORT_FACTORIES = "Nhập từ Excel…"
MENU_IMPORT_FACTORIES = "Nhập danh sách nhà máy (Excel)…"
FACTORY_IMPORT_TITLE = "Chọn file Excel danh sách nhà máy"
FACTORY_IMPORT_DONE = "Đã nhập danh sách nhà máy từ {file}:\nthêm mới {added}, cập nhật {updated} (tổng {total} nhà máy)."
FACTORY_IMPORT_EMPTY = "Không tìm thấy dòng nhà máy nào trong {file}."
FACTORY_IMPORT_TIP = "Nạp/cập nhật danh sách nhà máy từ file Excel (mỗi dòng một nhà máy). File gần nhất: {file}"
FACTORY_CODE = "Mã (số đầu tên file)"
FACTORY_TRANSPORT = "Transportation method (trống = theo Cài đặt)"
FACTORY_SCAC = "SCAC code (trống = theo Cài đặt)"
LBL_FACTORY_NOT_FOUND = "Nhà máy trong file: {text} - chưa có trong danh sách (hãy nhập danh sách nhà máy hoặc thêm mới)"

# --- đang chạy một phiên bản khác
INSTANCE_OLD_RUNNING = ("Một phiên bản cũ của EDI Assistant vẫn đang chạy (ở khay hệ thống, gần đồng hồ), "
                        "nên phiên bản {version} không mở được.\n\nChuột phải biểu tượng EDI Assistant ở khay > Thoát "
                        "(hoặc tắt trong Task Manager), rồi mở lại phiên bản này.")
INSTANCE_OTHER_VERSION = ("EDI Assistant {running} đang chạy (ở khay hệ thống). Đây là phiên bản {version}.\n\n"
                          "Đóng phiên bản {running} và mở {version}?")
INSTANCE_QUIT_TIMEOUT = ("EDI Assistant {running} chưa đóng. Hãy thoát nó từ biểu tượng ở khay (chuột phải > Thoát), "
                         "rồi mở lại phiên bản này.")
