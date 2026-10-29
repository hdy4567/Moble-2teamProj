#pragma once
#include <afxwin.h>
#include <string>
#include <vector>

struct OrderRow { CString id, time, product, quantity, status, region; };
struct OutboundRow { CString time, product, quantity, result, detail; };
struct StockRow { CString name, color, count, price, minStock; };
struct SensorRow { CString time, temperature, humidity; double temp=0, humid=0; };
struct FanRow { CString start, stop, duration; };

struct DashboardData {
    bool connected = false;
    bool hasSensor = false;
    CString error = L"DB 미연결";
    int pending = 0, processing = 0, totalStock = 0, lowStock = 0;
    int errorCount = 0, errorThreshold = 5;
    double temperature = 0, humidity = 0;
    bool fanOn = false;
    std::vector<OrderRow> orders;
    std::vector<OrderRow> processingOrders;
    std::vector<OutboundRow> outbound;
    std::vector<StockRow> stock;
    std::vector<SensorRow> sensors;
    std::vector<FanRow> fans;
};
