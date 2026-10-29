#pragma once

namespace Gdiplus { class FontFamily; }

// App-private fonts. Initialize before any UI is created, then Shutdown only
// after every window/font using these resources has been destroyed.
namespace UiFont {
bool Initialize();
void Shutdown();
const wchar_t* Family();
const Gdiplus::FontFamily* GdiPlusFamily();
}
