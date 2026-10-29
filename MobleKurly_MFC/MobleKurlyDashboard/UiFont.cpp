#include <afxwin.h>
#include <gdiplus.h>
#include "UiFont.h"
#include <array>
#include <memory>
#include <string>

#pragma comment(lib, "gdiplus.lib")

namespace {
constexpr std::array<const wchar_t*, 3> kFiles = {
    L"Pretendard-Regular.ttf", L"Pretendard-SemiBold.ttf", L"Pretendard-Bold.ttf"};
std::array<std::wstring, 3> paths;
std::array<bool, 3> registered{};
bool initialized = false;
bool nativeReady = false;
ULONG_PTR token = 0;
std::unique_ptr<Gdiplus::PrivateFontCollection> collection;
std::unique_ptr<Gdiplus::FontFamily> family;
}

namespace UiFont {
bool Initialize() {
  if (initialized) return nativeReady && family != nullptr;
  initialized = true;
  wchar_t executable[32768] = {};
  const DWORD length = GetModuleFileNameW(nullptr, executable, _countof(executable));
  if (!length || length >= _countof(executable)) return false;
  const std::wstring full(executable, length);
  const auto slash = full.find_last_of(L"\\/");
  if (slash == std::wstring::npos) return false;
  const std::wstring directory = full.substr(0, slash + 1) + L"fonts\\";
  for (size_t i = 0; i < kFiles.size(); ++i) {
    paths[i] = directory + kFiles[i];
    // FR_PRIVATE never installs fonts globally or changes other applications.
    registered[i] = AddFontResourceExW(paths[i].c_str(), FR_PRIVATE, nullptr) > 0;
  }
  nativeReady = registered[0] && registered[2];

  // Own a GDI+ lifetime independent of the dashboard's rendering token. The
  // family/collection remain alive until Shutdown, even when a frame closes.
  Gdiplus::GdiplusStartupInput startup;
  if (Gdiplus::GdiplusStartup(&token, &startup, nullptr) != Gdiplus::Ok) {
    token = 0;
    return false;
  }
  collection = std::make_unique<Gdiplus::PrivateFontCollection>();
  for (const auto& path : paths) collection->AddFontFile(path.c_str());
  auto candidate = std::make_unique<Gdiplus::FontFamily>(L"Pretendard", collection.get());
  if (candidate->GetLastStatus() == Gdiplus::Ok &&
      candidate->IsStyleAvailable(Gdiplus::FontStyleRegular) &&
      candidate->IsStyleAvailable(Gdiplus::FontStyleBold)) {
    family = std::move(candidate);
  }
  return nativeReady && family != nullptr;
}

void Shutdown() {
  // GDI+ objects must be released before their startup token is shut down.
  family.reset();
  collection.reset();
  if (token) { Gdiplus::GdiplusShutdown(token); token = 0; }
  for (size_t i = 0; i < paths.size(); ++i) {
    if (registered[i]) RemoveFontResourceExW(paths[i].c_str(), FR_PRIVATE, nullptr);
    registered[i] = false;
    paths[i].clear();
  }
  nativeReady = false;
  initialized = false;
}

const wchar_t* Family() { return nativeReady ? L"Pretendard" : L"Malgun Gothic"; }
const Gdiplus::FontFamily* GdiPlusFamily() { return family.get(); }
}
