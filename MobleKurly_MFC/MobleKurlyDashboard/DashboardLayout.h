#pragma once

// UI geometry only. No database, device, or authorization state belongs here.
namespace DashboardLayout {
struct Area { float x, y, w, h; };
inline constexpr float Width = 1536.f, Height = 1000.f;
inline constexpr Area WorkTab{330,16,160,40}, AdminTab{500,16,160,40};
inline constexpr Area Logout{930,18,100,36}, DbRefresh{1288,16,232,40};
inline constexpr Area Emergency{1350,76,170,100};
inline constexpr Area Orders{16,190,647,270}, Processing{16,472,647,228};
inline constexpr Area Outbound{16,712,647,260};
inline constexpr Area Camera{676,190,379,330}, ErrorBin{676,532,379,178};
inline constexpr Area Stock{676,722,379,250}, Graph{1067,190,453,326};
inline constexpr Area SensorLog{1067,528,453,188}, FanLog{1067,728,453,188};
inline constexpr Area Settlement{1067,928,453,44};
inline constexpr int OrderRows = 6;
inline constexpr Area Restock{Stock.x+12,Stock.y+201,Stock.w-24,36};
inline constexpr Area ClearBin{ErrorBin.x+16,ErrorBin.y+134,164,32};
inline constexpr Area BinHistory{ErrorBin.x+196,ErrorBin.y+134,167,32};
inline constexpr Area Reconnect{422,100,125,28};
inline constexpr Area Dispatch(int row) { return {Orders.x+542,Orders.y+77+row*30,83,24}; }
inline constexpr Area Retry(int row) { return {Processing.x+565,Processing.y+77+row*32,60,24}; }
}
