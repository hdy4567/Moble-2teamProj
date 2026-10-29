#include <afxwin.h>
#include "UiFont.h"
#include <afxcmn.h>
#include <afxdtctl.h> // CDateTimeCtrl declaration
#include <afxdlgs.h>
#include <shellapi.h>
#include <afxdisp.h>
#include <winspool.h>
#include <comdef.h>
#pragma comment(lib,"winspool.lib")
#include <sqlext.h>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <numeric>
#pragma comment(lib,"odbc32.lib")

using Rows = std::vector<std::vector<CString>>;
static CString Err(SQLSMALLINT t, SQLHANDLE h){SQLWCHAR state[6]={},msg[1024]={}; SQLINTEGER n=0;SQLSMALLINT len=0; if(SQL_SUCCEEDED(SQLGetDiagRecW(t,h,1,state,&n,msg,1023,&len)))return CString((wchar_t*)msg);return L"ODBC 오류";}
static CString Csv(CString s){s.Replace(L"\"",L"\"\"");return L"\""+s+L"\"";}
static bool SaveUtf8(const CString& path,const CString& content){CFile f; if(!f.Open(path,CFile::modeCreate|CFile::modeWrite|CFile::shareDenyWrite))return false;int n=WideCharToMultiByte(CP_UTF8,0,content,-1,nullptr,0,nullptr,nullptr);std::string bytes(n,'\0');WideCharToMultiByte(CP_UTF8,0,content,-1,bytes.data(),n,nullptr,nullptr);const unsigned char bom[]={0xef,0xbb,0xbf};f.Write(bom,3);f.Write(bytes.data(),n-1);f.Close();return true;}
static CString GroupNumber(CString value){
 value.Trim();if(value.IsEmpty())return value;
 CString raw=value;raw.Remove(L',');
 int begin=(raw[0]==L'-')?1:0;
 int dot=raw.Find(L'.');
 int integerEnd=dot>=0?dot:raw.GetLength();
 if(integerEnd<=begin)return value;
 for(int i=begin;i<integerEnd;++i)if(raw[i]<L'0'||raw[i]>L'9')return value;
 if(dot>=0){
  if(dot==raw.GetLength()-1)return value;
  for(int i=dot+1;i<raw.GetLength();++i)if(raw[i]<L'0'||raw[i]>L'9')return value;
 }
 // Format MySQL DECIMAL as whole won; leave the database values untouched.
 CString integral=raw.Left(integerEnd);
 if(dot>=0 && dot+1<raw.GetLength() && raw[dot+1]>=L'5'){
  int i=integral.GetLength()-1;
  while(i>=begin && integral[i]==L'9'){integral.SetAt(i,L'0');--i;}
  if(i>=begin)integral.SetAt(i,integral[i]+1);
  else integral.Insert(begin,L"1");
 }
 CString out;int digits=0;
 for(int i=integral.GetLength()-1;i>=begin;--i){
  if(digits&&digits%3==0)out=L","+out;
  out=integral.Mid(i,1)+out;++digits;
 }
 if(begin)out=L"-"+out;
 return out;
}
class Db{
 SQLHENV env=SQL_NULL_HENV; SQLHDBC dbc=SQL_NULL_HDBC;
public:
 ~Db(){Close();}
 void Close(){if(dbc){SQLDisconnect(dbc);SQLFreeHandle(SQL_HANDLE_DBC,dbc);dbc=SQL_NULL_HDBC;}if(env){SQLFreeHandle(SQL_HANDLE_ENV,env);env=SQL_NULL_HENV;}}
 bool Connect(const CString& ini,CString& err){Close();wchar_t driver[128]={},host[128]={},port[32]={},db[128]={},user[128]={},pwd[256]={};
 GetPrivateProfileStringW(L"mysql",L"driver",L"MySQL ODBC 26.7 Unicode Driver",driver,128,ini);
 GetPrivateProfileStringW(L"mysql",L"host",L"127.0.0.1",host,128,ini);GetPrivateProfileStringW(L"mysql",L"port",L"3306",port,32,ini);
 GetPrivateProfileStringW(L"mysql",L"database",L"moblekurly",db,128,ini);GetPrivateProfileStringW(L"mysql",L"user",L"moblekurly",user,128,ini);GetPrivateProfileStringW(L"mysql",L"password",L"",pwd,256,ini);
 // The EXE's config.ini may be an outdated blank copy. Also check the
 // project folder so the user's edited configuration is respected.
 if(!*pwd){
  CString folder=ini.Left(ini.ReverseFind(L'\\'));
  for(int level=0;level<4 && !*pwd;++level){
   int slash=folder.ReverseFind(L'\\');if(slash<0)break;
   folder=folder.Left(slash);
   CString candidate=folder+L"\\config.ini";
   if(candidate.CompareNoCase(ini)==0 || GetFileAttributesW(candidate)==INVALID_FILE_ATTRIBUTES)continue;
   wchar_t altPwd[256]={};
   GetPrivateProfileStringW(L"mysql",L"password",L"",altPwd,256,candidate);
   if(!*altPwd)continue;
   wcscpy_s(pwd,altPwd);
   GetPrivateProfileStringW(L"mysql",L"driver",L"MySQL ODBC 26.7 Unicode Driver",driver,128,candidate);
   GetPrivateProfileStringW(L"mysql",L"host",L"127.0.0.1",host,128,candidate);
   GetPrivateProfileStringW(L"mysql",L"port",L"3306",port,32,candidate);
   GetPrivateProfileStringW(L"mysql",L"database",L"moblekurly",db,128,candidate);
   GetPrivateProfileStringW(L"mysql",L"user",L"moblekurly",user,128,candidate);
  }
 }
 if(!*pwd){err=L"서버 연결 정보를 확인해주세요.\n설정 파일: "+ini;return false;}
 if(!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_ENV,SQL_NULL_HANDLE,&env))){err=L"서버 연결을 준비하지 못했습니다.";return false;}
 SQLSetEnvAttr(env,SQL_ATTR_ODBC_VERSION,(SQLPOINTER)SQL_OV_ODBC3,0);
 if(!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_DBC,env,&dbc))){err=L"서버에 연결하지 못했습니다.";Close();return false;}
 SQLSetConnectAttr(dbc,SQL_ATTR_LOGIN_TIMEOUT,(SQLPOINTER)5,0);
 CString c;c.Format(L"DRIVER={%s};SERVER=%s;PORT=%s;DATABASE=%s;UID=%s;PWD=%s;CHARSET=utf8mb4;OPTION=3;",driver,host,port,db,user,pwd);SecureZeroMemory(pwd,sizeof(pwd));
 SQLRETURN r=SQLDriverConnectW(dbc,nullptr,(SQLWCHAR*)(LPCWSTR)c,SQL_NTS,nullptr,0,nullptr,SQL_DRIVER_NOPROMPT);
 if(!SQL_SUCCEEDED(r)){err=Err(SQL_HANDLE_DBC,dbc);Close();return false;}return true;}
 bool Query(const CString& sql,Rows& rows,CString& err){rows.clear();if(!dbc){err=L"서버에 연결되지 않았습니다.";return false;}SQLHSTMT st=SQL_NULL_HSTMT;if(!SQL_SUCCEEDED(SQLAllocHandle(SQL_HANDLE_STMT,dbc,&st))){err=L"조회 요청을 준비하지 못했습니다.";return false;}
 SQLSetStmtAttr(st,SQL_ATTR_QUERY_TIMEOUT,(SQLPOINTER)15,0);SQLRETURN r=SQLExecDirectW(st,(SQLWCHAR*)(LPCWSTR)sql,SQL_NTS);if(!SQL_SUCCEEDED(r)){err=Err(SQL_HANDLE_STMT,st);SQLFreeHandle(SQL_HANDLE_STMT,st);return false;}
 SQLSMALLINT n=0;SQLNumResultCols(st,&n);while((r=SQLFetch(st))==SQL_SUCCESS||r==SQL_SUCCESS_WITH_INFO){std::vector<CString> row;for(SQLUSMALLINT i=1;i<=n;++i){SQLWCHAR buf[4096]={};SQLLEN ind=0;SQLRETURN rc=SQLGetData(st,i,SQL_C_WCHAR,buf,sizeof(buf),&ind);row.push_back(SQL_SUCCEEDED(rc)&&ind!=SQL_NULL_DATA?CString((wchar_t*)buf):CString(L""));}rows.push_back(row);}
 bool ok=r==SQL_NO_DATA;if(!ok)err=Err(SQL_HANDLE_STMT,st);SQLFreeHandle(SQL_HANDLE_STMT,st);return ok;}
};

class RevenueGraph : public CWnd {
public:
 std::vector<double> values; std::vector<CString> labels;
 std::vector<CPoint> points;
 int hovered=-1;
 void SetRows(const Rows& rows,int tab){values.clear();labels.clear();points.clear();hovered=-1;if(tab==0){for(const auto& r:rows){if(r.size()<4)continue;CString v=r[3];v.Remove(L',');values.push_back(_wtof(v));labels.push_back(r[0]);}}if(GetSafeHwnd())Invalidate(TRUE);}
 afx_msg BOOL OnEraseBkgnd(CDC*){return TRUE;}
 afx_msg void OnMouseLeave(){hovered=-1;Invalidate(FALSE);}
 afx_msg void OnMouseMove(UINT flags,CPoint pos){TRACKMOUSEEVENT tme={sizeof(tme),TME_LEAVE,m_hWnd,0};TrackMouseEvent(&tme);int nearest=-1;double best=225.0;for(int i=0;i<(int)points.size();++i){double dx=pos.x-points[i].x,dy=pos.y-points[i].y,d=dx*dx+dy*dy;if(d<best){best=d;nearest=i;}}if(nearest!=hovered){hovered=nearest;Invalidate(FALSE);}CWnd::OnMouseMove(flags,pos);}
 afx_msg void OnPaint(){CPaintDC dc(this);CRect rc;GetClientRect(&rc);dc.FillSolidRect(&rc,RGB(255,255,255));dc.SetBkMode(TRANSPARENT);CFont font;font.CreateFontW(-15,0,0,0,FW_NORMAL,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,UiFont::Family());CFont* old=dc.SelectObject(&font);dc.SetTextColor(RGB(43,61,85));dc.TextOutW(18,10,L"매출 추이");CRect plot(83,47,rc.right-35,rc.bottom-38);points.clear();if(plot.Width()<80||plot.Height()<55){dc.SelectObject(old);return;}if(values.empty()){dc.SetTextColor(RGB(120,132,150));dc.TextOutW(18,55,L"기간별 매출 탭에서 그래프를 확인할 수 있습니다.");dc.SelectObject(old);return;}double mx=1;for(double v:values)mx=std::max(mx,v);CPen grid(PS_SOLID,1,RGB(228,233,241)),line(PS_SOLID,2,RGB(37,112,195));for(int i=0;i<=4;++i){int y=plot.bottom-i*plot.Height()/4;CPen* p=dc.SelectObject(&grid);dc.MoveTo(plot.left,y);dc.LineTo(plot.right,y);dc.SelectObject(p);CString s;s.Format(L"%.0f",mx*i/4);{CString commas;int digits=0;for(int k=s.GetLength()-1;k>=0;--k){if(digits&&digits%3==0)commas=L","+commas;commas=s.Mid(k,1)+commas;++digits;}s=commas;}dc.SetTextColor(RGB(120,132,150));dc.DrawText(s,CRect(0,y-10,plot.left-8,y+10),DT_RIGHT|DT_SINGLELINE|DT_VCENTER);}int n=(int)values.size();CPen* oldPen=dc.SelectObject(&line);for(int i=0;i<n;++i){int x=plot.left+(n==1?plot.Width()/2:i*plot.Width()/(n-1)),y=plot.bottom-(int)(values[i]/mx*plot.Height());points.push_back(CPoint(x,y));if(i==0)dc.MoveTo(x,y);else dc.LineTo(x,y);}dc.SelectObject(oldPen);CBrush dot(RGB(37,112,195));for(int i=0;i<n;++i){CPoint p=points[i];int radius=i==hovered?6:4;CRect d(p.x-radius,p.y-radius,p.x+radius+1,p.y+radius+1);CBrush* previous=dc.SelectObject(&dot);dc.Ellipse(&d);dc.SelectObject(previous);if(n<=12&&(i==0||(n<12&&i==n-1)||n<=7||i%2==0)){CString label=labels[i];if(label.GetLength()>5)label=label.Right(5);dc.SetTextColor(RGB(90,104,125));dc.DrawText(label,CRect(p.x-37,plot.bottom+5,p.x+37,plot.bottom+27),DT_CENTER|DT_SINGLELINE);}}
 if(hovered>=0&&hovered<(int)points.size()){CString amount;amount.Format(L"%.0f",values[hovered]);CString formatted;int digits=0;for(int i=amount.GetLength()-1;i>=0;--i){if(digits&&digits%3==0)formatted=L","+formatted;formatted=amount.Mid(i,1)+formatted;++digits;}CString tip=labels[hovered]+L"  |  "+formatted+L"원";CRect bubble(0,0,235,29);int bx=points[hovered].x+12,by=points[hovered].y-37;if(bx+bubble.Width()>rc.right-6)bx=points[hovered].x-bubble.Width()-12;if(by<30)by=points[hovered].y+12;bubble.OffsetRect(bx,by);dc.FillSolidRect(bubble,RGB(19,55,91));dc.SetTextColor(RGB(255,255,255));dc.DrawText(tip,bubble,DT_CENTER|DT_VCENTER|DT_SINGLELINE|DT_END_ELLIPSIS);}
 dc.SelectObject(old);}
 DECLARE_MESSAGE_MAP()
};
BEGIN_MESSAGE_MAP(RevenueGraph,CWnd)
 ON_WM_PAINT() ON_WM_ERASEBKGND() ON_WM_MOUSEMOVE() ON_WM_MOUSELEAVE()
END_MESSAGE_MAP()

class SettlementButton final : public CButton {
public:
 bool primary = false;
 void DrawItem(LPDRAWITEMSTRUCT item) override {
  CDC dc; dc.Attach(item->hDC);
  CRect r(item->rcItem);
  const bool down = (item->itemState & ODS_SELECTED) != 0;
  const bool disabled = (item->itemState & ODS_DISABLED) != 0;
  const COLORREF fill = disabled ? RGB(233,237,241) : primary
      ? (down ? RGB(19,55,91) : RGB(32,120,180))
      : (down ? RGB(225,237,247) : RGB(255,255,255));
  CBrush brush(fill); CPen pen(PS_SOLID,1,primary ? RGB(32,120,180) : RGB(200,210,222));
  CBrush* oldBrush=dc.SelectObject(&brush); CPen* oldPen=dc.SelectObject(&pen);
  dc.RoundRect(r,CPoint(10,10));
  dc.SelectObject(oldPen); dc.SelectObject(oldBrush);
  CString text; GetWindowTextW(text);
  dc.SetBkMode(TRANSPARENT);
  dc.SetTextColor(disabled ? RGB(125,135,146) : primary ? RGB(255,255,255) : RGB(37,51,67));
  CFont* oldFont=dc.SelectObject(GetFont());
  dc.DrawText(text,r,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
  dc.SelectObject(oldFont);
  if(item->itemState & ODS_FOCUS){r.DeflateRect(4,4);dc.DrawFocusRect(r);}
  dc.Detach();
 }
};

enum {ID_PERIOD=100,ID_DATE=101,ID_REFRESH=102,ID_CSV=103,ID_HTML=104,ID_TABS=105,ID_LIST=106,ID_YEAR=108,ID_MONTH=109,ID_REGION=110};
class SettlementFrame:public CFrameWnd{
public:
 SettlementFrame(bool compact=false, CWnd* parent=nullptr, const CRect& rect=CRect(0,0,820,830)):
     compact_(compact), embedded_(parent != nullptr){
  const CString cls=AfxRegisterWndClass(CS_HREDRAW|CS_VREDRAW, ::LoadCursor(nullptr,IDC_ARROW), (HBRUSH)(COLOR_WINDOW+1), nullptr);
  if(!cls.IsEmpty()) Create(cls,compact_?L"MobleKurly - 작업 결산":L"MobleKurly - 매출 결산",
      embedded_ ? (WS_CHILD|WS_CLIPCHILDREN) : WS_OVERLAPPEDWINDOW,
      embedded_ ? rect : (compact_?CRect(180,130,920,690):CRect(100,70,1100,950)),parent);
 }
private:
 bool compact_=false;bool embedded_=false;
 Db db; CString ini,periodStart,periodEnd;CComboBox period,yearPicker,monthPicker,regionPicker;CDateTimeCtrl datePicker;SettlementButton refresh,html;CStatic summary,status,brand,subtitle,periodLabel,reportLabel,kpiOrders,kpiQuantity,kpiRevenue,kpiErrors,kpiOrderTitle,kpiQuantityTitle,kpiRevenueTitle,kpiErrorsTitle;CBrush pageBrush,cardBrush;CFont uiFont,uiBold,uiKpi;CTabCtrl tabs;CListCtrl list;RevenueGraph graph;Rows data;std::vector<CString> headers;bool connected=false;
 CString RegionWhere(const CString& alias=L"o")const{
  int selected=regionPicker.GetCurSel();if(selected<=0)return L"";
  CString region;
  if(selected==1)region=L"서울";else if(selected==2)region=L"경기";else region=L"충청";
  // Region enum values can be Korean or English; accept both established conventions.
  CString english=selected==1?L"SEOUL":selected==2?L"GYEONGGI":L"CHUNGCHEONG";
  CString sql;sql.Format(L" AND (%s.delivery_region='%s' OR %s.delivery_region='%s')",alias.GetString(),region.GetString(),alias.GetString(),english.GetString());return sql;
 }
 CString RegionName()const{int n=regionPicker.GetCurSel();return n==1?L"서울":n==2?L"경기":n==3?L"충청":L"전체 지역";}
 CString Scope()const{CString where;where.Format(L" >= '%s' AND ",periodStart.GetString());return where;}
 CString Between(const CString& col)const{CString s;s.Format(L"%s >= '%s' AND %s < '%s'",col.GetString(),periodStart.GetString(),col.GetString(),periodEnd.GetString());return s;}
 void Dates(){CTime t;datePicker.GetTime(t);int sel=period.GetCurSel();
 int year=t.GetYear(),month=t.GetMonth();
 if(sel!=0){year=2026;month=1;CString v;yearPicker.GetLBText(yearPicker.GetCurSel(),v);year=_wtoi(v);if(sel==1){monthPicker.GetLBText(monthPicker.GetCurSel(),v);month=_wtoi(v);}}
 CTime a(year,sel==2?1:month,sel==0?t.GetDay():1,0,0,0);CTime b;
 if(sel==0)b=a+CTimeSpan(1,0,0,0);else if(sel==1)b=CTime(a.GetYear()+(a.GetMonth()==12),a.GetMonth()==12?1:a.GetMonth()+1,1,0,0,0);else b=CTime(a.GetYear()+1,1,1,0,0,0);
 periodStart=a.Format(L"%Y-%m-%d");periodEnd=b.Format(L"%Y-%m-%d");}
 void SetColumns(const std::vector<CString>& cols){list.DeleteAllItems();while(list.DeleteColumn(0)){}headers=cols;CRect listRect;list.GetClientRect(&listRect);
  const int count=(int)cols.size(),available=std::max(240,listRect.Width()-GetSystemMetrics(SM_CXVSCROLL)-6);
  const int first=std::min(220,std::max(100,available*34/100));
  for(int i=0;i<count;++i){
   int width=(i==0)?first:std::max(70,(available-first)/std::max(1,count-1));
   list.InsertColumn(i,cols[i],i==0?LVCFMT_LEFT:LVCFMT_RIGHT,width);
  }}
 void FitListColumns(){
  if(!::IsWindow(list.GetSafeHwnd()) || headers.empty())return;
  CRect r;list.GetClientRect(&r);
  const int count=static_cast<int>(headers.size());
  const int available=std::max(240,r.Width()-GetSystemMetrics(SM_CXVSCROLL)-6);
  const int first=std::min(240,std::max(100,available*34/100));
  const int other=std::max(70,(available-first)/std::max(1,count-1));
  for(int i=0;i<count;++i)list.SetColumnWidth(i,i==0?first:other);
 }
 void ShowRows(){list.SetRedraw(FALSE);list.DeleteAllItems();for(int i=0;i<(int)data.size();++i){if(data[i].empty())continue;list.InsertItem(i,data[i][0]);for(int j=1;j<(int)data[i].size();++j)list.SetItemText(i,j,GroupNumber(data[i][j]));}list.SetRedraw(TRUE);list.Invalidate();}
 void Reload(){
  if(!connected)return;
  Dates();CString err,q;Rows totals;
  // Accounting policy: COMPLETED means delivered as well as order-completed.
  // Entire order is recognized only when every line has been fully shipped.
  // If the team's COMPLETED status means something else, a separate delivery signal is required.
  CString eligible=L"o.status = 'COMPLETED' AND o.completed_at IS NOT NULL "
   L"AND NOT EXISTS (SELECT 1 FROM order_items missing WHERE missing.order_id=o.order_id "
   L"AND COALESCE(missing.shipped_qty,0) < missing.quantity) "
   L"AND EXISTS (SELECT 1 FROM order_items present WHERE present.order_id=o.order_id)";
  CString periodFilter=Between(L"o.completed_at")+RegionWhere();
  q.Format(L"SELECT COUNT(DISTINCT o.order_id),COALESCE(SUM(oi.shipped_qty),0),"
   L"COALESCE(SUM(oi.shipped_qty*oi.unit_price),0) "
   L"FROM orders o JOIN order_items oi ON oi.order_id=o.order_id "
   L"WHERE %s AND %s",periodFilter.GetString(),eligible.GetString());
  if(!db.Query(q,totals,err)){status.SetWindowTextW(L"매출 집계 실패: "+err);return;}
  if(!totals.empty()&&totals[0].size()>=3){
   kpiOrders.SetWindowTextW(GroupNumber(totals[0][0])+L" 건");
   kpiQuantity.SetWindowTextW(GroupNumber(totals[0][1])+L" 개");
   kpiRevenue.SetWindowTextW(GroupNumber(totals[0][2])+L" 원");
  }
  Rows errors;CString eq;
  eq.Format(L"SELECT COUNT(*) FROM outbound_logs l WHERE %s AND "
   L"l.expected_product_id IS NOT NULL AND l.detected_product_id IS NOT NULL "
   L"AND l.expected_product_id <> l.detected_product_id",Between(L"l.created_at").GetString());
  if(regionPicker.GetCurSel()>0){
   eq=L"SELECT COUNT(*) FROM outbound_logs l JOIN outbound_jobs j ON j.job_id=l.job_id "
      L"JOIN order_items oi ON oi.item_id=j.item_id JOIN orders o ON o.order_id=oi.order_id "
      L"WHERE "+Between(L"l.created_at")+RegionWhere()+
      L" AND l.expected_product_id IS NOT NULL AND l.detected_product_id IS NOT NULL "
      L"AND l.expected_product_id <> l.detected_product_id";
  }
  if(db.Query(eq,errors,err)&&!errors.empty()&&!errors[0].empty())
   kpiErrors.SetWindowTextW(GroupNumber(errors[0][0])+L" 건");
  else kpiErrors.SetWindowTextW(L"조회 불가");
  for(CStatic* value : {&kpiOrders,&kpiQuantity,&kpiRevenue,&kpiErrors}){value->Invalidate(TRUE);value->UpdateWindow();}
  summary.SetWindowTextW(L"DB 연결 완료  |  매출 인정 기준: 주문 완료 + 배송 완료(전 품목 출고) / 완료일 기준");summary.Invalidate(TRUE);summary.UpdateWindow();
  int tab=tabs.GetCurSel();data.clear();std::vector<CString> cols;
  CString grouping,groupBy;
  if(period.GetCurSel()==2){grouping=L"DATE_FORMAT(o.completed_at,'%Y-%m')";groupBy=L"DATE_FORMAT(o.completed_at,'%Y-%m')";}
  else{grouping=L"DATE_FORMAT(o.completed_at,'%Y-%m-%d')";groupBy=grouping;}
  switch(tab){
  case 0:
   cols={L"완료 날짜",L"완료 주문",L"배송 수량",L"인정 매출액 (원)"};
   q.Format(L"SELECT %s,COUNT(DISTINCT o.order_id),COALESCE(SUM(oi.shipped_qty),0),"
    L"COALESCE(SUM(oi.shipped_qty*oi.unit_price),0) FROM orders o "
    L"JOIN order_items oi ON oi.order_id=o.order_id WHERE %s AND %s "
    L"GROUP BY %s ORDER BY %s",grouping.GetString(),periodFilter.GetString(),eligible.GetString(),groupBy.GetString(),groupBy.GetString());break;
  case 1:
   cols={L"상품명",L"배송 수량",L"인정 매출액 (원)"};
   q.Format(L"SELECT COALESCE(p.name,'삭제된 상품'),COALESCE(SUM(oi.shipped_qty),0),"
    L"COALESCE(SUM(oi.shipped_qty*oi.unit_price),0) FROM orders o "
    L"JOIN order_items oi ON oi.order_id=o.order_id "
    L"LEFT JOIN products p ON p.product_id=oi.product_id WHERE %s AND %s "
    L"GROUP BY oi.product_id,p.name ORDER BY SUM(oi.shipped_qty*oi.unit_price) DESC",periodFilter.GetString(),eligible.GetString());break;
  case 2:
   cols={L"주문 상태",L"주문 건수"};
   q.Format(L"SELECT o.status,COUNT(*) FROM orders o WHERE %s "
    L"GROUP BY o.status ORDER BY COUNT(*) DESC",(Between(L"o.ordered_at")+RegionWhere()).GetString());break;
  case 3:
   cols={L"출고 결과",L"목적지",L"처리 횟수"};
   if(regionPicker.GetCurSel()==0){
    q.Format(L"SELECT l.result,l.destination,COUNT(*) FROM outbound_logs l WHERE %s "
     L"GROUP BY l.result,l.destination ORDER BY COUNT(*) DESC",Between(L"l.created_at").GetString());
   }else{
    q=L"SELECT l.result,l.destination,COUNT(*) FROM outbound_logs l "
      L"JOIN outbound_jobs j ON j.job_id=l.job_id JOIN order_items oi ON oi.item_id=j.item_id "
      L"JOIN orders o ON o.order_id=oi.order_id WHERE "+Between(L"l.created_at")+RegionWhere()+
      L" GROUP BY l.result,l.destination ORDER BY COUNT(*) DESC";
   }break;
  default:
   cols={L"배송 지역",L"완료 주문",L"배송 수량",L"인정 매출액 (원)"};
   q.Format(L"SELECT o.delivery_region,COUNT(DISTINCT o.order_id),COALESCE(SUM(oi.shipped_qty),0),"
    L"COALESCE(SUM(oi.shipped_qty*oi.unit_price),0) FROM orders o "
    L"JOIN order_items oi ON oi.order_id=o.order_id WHERE %s AND %s "
    L"GROUP BY o.delivery_region ORDER BY SUM(oi.shipped_qty*oi.unit_price) DESC",periodFilter.GetString(),eligible.GetString());break;
  }
  SetColumns(cols);err.Empty();
  if(!db.Query(q,data,err)){status.SetWindowTextW(L"상세 조회 실패: "+err);return;}
  ShowRows();graph.SetRows(data,tab);
  CString m;m.Format(L"배송 완료 결산 | %s | %s ~ %s (종료일 미포함) | %d행 | DB 읽기 전용",RegionName().GetString(),periodStart.GetString(),periodEnd.GetString(),(int)data.size());
  status.SetWindowTextW(m);Invalidate(TRUE);
 }
 CString ReportCsv(){CString out;for(size_t j=0;j<headers.size();++j){if(j)out+=L",";out+=Csv(headers[j]);}out+=L"\r\n";for(auto&r:data){for(size_t j=0;j<r.size();++j){if(j)out+=L",";out+=Csv(r[j]);}out+=L"\r\n";}return out;}
 bool ExportPdf(const CString& path,CString& error){
  HDC dc=CreateDCW(L"WINSPOOL",L"Microsoft Print to PDF",nullptr,nullptr);
  if(!dc){error=L"Microsoft Print to PDF 프린터가 없습니다.";return false;}
  DOCINFOW info={};info.cbSize=sizeof(info);info.lpszDocName=L"MobleKurly Settlement Report";info.lpszOutput=path;
  if(StartDocW(dc,&info)<=0){error=L"PDF 출력 작업을 시작하지 못했습니다.";DeleteDC(dc);return false;}
  const int dpi=GetDeviceCaps(dc,LOGPIXELSY),w=GetDeviceCaps(dc,HORZRES),h=GetDeviceCaps(dc,VERTRES);
  const int margin=dpi*55/100,usable=w-2*margin,rowH=dpi*38/100;
  HFONT fontTitle=CreateFontW(-dpi*30/100,0,0,0,FW_BOLD,FALSE,FALSE,FALSE,HANGEUL_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Malgun Gothic");
  HFONT fontHead=CreateFontW(-dpi*14/100,0,0,0,FW_BOLD,FALSE,FALSE,FALSE,HANGEUL_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Malgun Gothic");
  HFONT fontBody=CreateFontW(-dpi*12/100,0,0,0,FW_NORMAL,FALSE,FALSE,FALSE,HANGEUL_CHARSET,0,0,CLEARTYPE_QUALITY,0,L"Malgun Gothic");
  const COLORREF navy=RGB(30,49,77),muted=RGB(94,111,133),pale=RGB(239,244,249),line=RGB(219,227,235);
  int y=margin,page=0;bool ok=true;
  auto rect=[&](int x,int yy,int ww,int hh,COLORREF color){RECT r={x,yy,x+ww,yy+hh};HBRUSH br=CreateSolidBrush(color);FillRect(dc,&r,br);DeleteObject(br);};
  auto label=[&](const CString& str,int x,int yy,int ww,int hh,HFONT font,COLORREF color,UINT align=DT_LEFT){SelectObject(dc,font);SetTextColor(dc,color);SetBkMode(dc,TRANSPARENT);RECT r={x,yy,x+ww,yy+hh};DrawTextW(dc,str,-1,&r,align|DT_VCENTER|DT_SINGLELINE|DT_END_ELLIPSIS|DT_NOPREFIX);};
  auto start=[&](){if(StartPage(dc)<=0)return false;++page;y=margin;rect(margin,y,usable,dpi/16,navy);y+=dpi/10;label(L"MOBLE KURLY  /  SETTLEMENT",margin,y,usable,dpi/4,fontHead,muted);y+=dpi/3;label(L"매출 결산 보고서",margin,y,usable,dpi*42/100,fontTitle,navy);y+=dpi*48/100;CString periodText=L"조회 기간  "+periodStart+L" ~ "+periodEnd+L" (종료일 미포함)  |  지역: "+RegionName();label(periodText,margin,y,usable,dpi/4,fontBody,muted);y+=dpi*34/100;rect(margin,y,usable,2,line);y+=dpi/5;return true;};
  auto footer=[&](){rect(margin,h-margin-dpi/4,usable,2,line);CString stamp=CTime::GetCurrentTime().Format(L"생성일  %Y-%m-%d %H:%M");label(stamp,margin,h-margin-dpi/6,usable/2,dpi/5,fontBody,muted);CString pg;pg.Format(L"Page %d",page);label(pg,margin+usable/2,h-margin-dpi/6,usable/2,dpi/5,fontBody,muted,DT_RIGHT);};
  if(!start())ok=false;
  if(ok){
   label(L"결산 요약",margin,y,usable,dpi/3,fontHead,navy);y+=dpi*38/100;
   // KPI captions and values are separate CStatic controls on the dashboard.
   // Read both controls directly; the old CRLF split rendered a dash instead of the value.
   CString kpiNames[4],kpiValues[4];
   CStatic* kpiTitleControls[4]={&kpiOrderTitle,&kpiQuantityTitle,&kpiRevenueTitle,&kpiErrorsTitle};
   CStatic* kpiValueControls[4]={&kpiOrders,&kpiQuantity,&kpiRevenue,&kpiErrors};
   for(int i=0;i<4;++i){kpiTitleControls[i]->GetWindowTextW(kpiNames[i]);kpiValueControls[i]->GetWindowTextW(kpiValues[i]);}
   const int gap=dpi/12,cardW=(usable-gap*3)/4,cardH=dpi*68/100;
   for(int i=0;i<4;++i){
    int x=margin+i*(cardW+gap);rect(x,y,cardW,cardH,pale);
    label(kpiNames[i],x+dpi/12,y+dpi/12,cardW-dpi/6,dpi/5,fontBody,muted);
    label(kpiValues[i],x+dpi/12,y+dpi*31/100,cardW-dpi/6,dpi/4,fontHead,navy);
   }
   y+=cardH+dpi*30/100;
   // The PDF always contains a revenue bar chart, regardless of the selected detail tab.
   Rows chartRows;
   if(tabs.GetCurSel()==0)chartRows=data;
   else if(connected){
    CString eligible=L"o.status = 'COMPLETED' AND o.completed_at IS NOT NULL "
      L"AND NOT EXISTS (SELECT 1 FROM order_items missing WHERE missing.order_id=o.order_id "
      L"AND COALESCE(missing.shipped_qty,0) < missing.quantity) "
      L"AND EXISTS (SELECT 1 FROM order_items present WHERE present.order_id=o.order_id)";
    CString grouping=period.GetCurSel()==2?L"DATE_FORMAT(o.completed_at,'%Y-%m')":L"DATE_FORMAT(o.completed_at,'%Y-%m-%d')";
    CString query,err;
    query.Format(L"SELECT %s, COUNT(DISTINCT o.order_id), SUM(oi.shipped_qty), "
      L"COALESCE(SUM(oi.shipped_qty*oi.unit_price),0) FROM orders o "
      L"JOIN order_items oi ON oi.order_id=o.order_id WHERE %s AND %s "
      L"GROUP BY %s ORDER BY %s",grouping.GetString(),(Between(L"o.completed_at")+RegionWhere()).GetString(),eligible.GetString(),grouping.GetString(),grouping.GetString());
    if(!db.Query(query,chartRows,err)){error=L"PDF 기간별 매출 조회 실패: "+err;ok=false;}
   }
   const int chartH=dpi*18/10;
   if(y+chartH>h-margin-dpi/2){footer();if(EndPage(dc)<=0||!start())ok=false;}
   if(ok){
    label(tabs.GetCurSel()==4?L"지역별 매출 막대그래프":L"기간별 매출 막대그래프",margin,y,usable,dpi/3,fontHead,navy);y+=dpi*38/100;
    const int chartTop=y,plotH=dpi*98/100;
    // Reserve enough space for the widest Y-axis currency label.
    double maxForAxis=1.0;for(const auto& r:chartRows){if(r.size()>3){CString v=r[3];v.Remove(L',');maxForAxis=std::max(maxForAxis,_wtof(v));}}
    CString longestTick;longestTick.Format(L"%.0f",maxForAxis);longestTick=GroupNumber(longestTick);
    SelectObject(dc,fontBody);SIZE tickSize={};GetTextExtentPoint32W(dc,longestTick,longestTick.GetLength(),&tickSize);
    const int axisX=margin+std::max(dpi*75/100,static_cast<int>(tickSize.cx)+dpi*24/100);
    const int plotW=std::max(dpi,margin+usable-axisX-dpi/12);
    double maxVal=1.0;for(const auto& r:chartRows){if(r.size()>3){CString v=r[3];v.Remove(L',');maxVal=std::max(maxVal,_wtof(v));}}
    for(int tick=0;tick<=4;++tick){int gy=chartTop+plotH-tick*plotH/4;rect(axisX,gy,plotW,1,line);
     CString number;number.Format(L"%.0f",maxVal*tick/4);number=GroupNumber(number);
     label(number,margin,gy-dpi/10,axisX-margin-dpi/10,dpi/5,fontBody,muted,DT_RIGHT);
    }
    int n=(int)chartRows.size();if(n>0){int slot=plotW/n;int barW=std::max(2,std::min(dpi*34/100,slot*7/10));
     for(int i=0;i<n;++i){const auto& r=chartRows[i];if(r.size()<4)continue;CString v=r[3];v.Remove(L',');double amount=std::max(0.0,_wtof(v));
      int bh=(int)(amount/maxVal*plotH);int x=axisX+i*slot+(slot-barW)/2;
      if(bh>0)rect(x,chartTop+plotH-bh,barW,bh,RGB(48,111,183));
      // Keep the horizontal-axis labels readable: show at most 7 date labels.
      const int labelStep=std::max(1,(n+6)/7);
      if(i%labelStep==0 && !(n==12 && i==n-1)){
       CString t=r[0];
       // Day: MM-DD, month: YYYY-MM, year: YYYY.
       if(t.GetLength()>=10)t=t.Mid(5,5);
       else if(t.GetLength()==7)t=t;
       const int labelWidth=std::max(slot,dpi*54/100);
       int labelX=x+barW/2-labelWidth/2;
       // Use full-width label and prevent printer clipping/overlap.
       if(labelX<axisX)labelX=axisX;
       if(labelX+labelWidth>axisX+plotW)labelX=axisX+plotW-labelWidth;
       label(t,labelX,chartTop+plotH+dpi/20,labelWidth,dpi/4,fontBody,muted,DT_CENTER);
      }
     }
    }else label(L"선택 기간의 매출 데이터가 없습니다.",axisX,chartTop+dpi/3,plotW,dpi/3,fontBody,muted);
    y=chartTop+plotH+dpi*52/100;
   }

   // Regional PDF summary is always included, even on the period-sales tab.
   if(ok){
    Rows regions;
    if(connected){
     CString eligible=L"o.status = 'COMPLETED' AND o.completed_at IS NOT NULL "
      L"AND NOT EXISTS (SELECT 1 FROM order_items missing WHERE missing.order_id=o.order_id "
      L"AND COALESCE(missing.shipped_qty,0) < missing.quantity) "
      L"AND EXISTS (SELECT 1 FROM order_items present WHERE present.order_id=o.order_id)";
     CString sql,err;
     sql.Format(L"SELECT o.delivery_region,COUNT(DISTINCT o.order_id),COALESCE(SUM(oi.shipped_qty),0),"
      L"COALESCE(SUM(oi.shipped_qty*oi.unit_price),0) FROM orders o "
      L"JOIN order_items oi ON oi.order_id=o.order_id WHERE %s AND %s "
      L"GROUP BY o.delivery_region ORDER BY o.delivery_region",
      (Between(L"o.completed_at")+RegionWhere()).GetString(),eligible.GetString());
     if(!db.Query(sql,regions,err)){error=L"PDF 지역별 매출 조회 실패: "+err;ok=false;}
    }
    if(y+dpi*27/10>h-margin-dpi/2){footer();if(EndPage(dc)<=0||!start())ok=false;}
    if(ok){
     label(L"지역별 매출 비교",margin,y,usable,dpi/3,fontHead,navy);y+=dpi*40/100;
     double peak=1.0;for(const auto& r:regions)if(r.size()>3){CString v=r[3];v.Remove(L',');peak=std::max(peak,_wtof(v));}
     const int barX=margin+dpi*70/100,amountW=dpi*125/100;
     const int barW=std::max(dpi/2,usable-dpi*70/100-amountW-dpi/8);
     for(const auto& r:regions){
      if(y+rowH>h-margin-dpi/2){footer();if(EndPage(dc)<=0||!start())ok=false;}
      if(!ok)break;if(r.empty())continue;
      label(r[0],margin,y,dpi*65/100,rowH,fontBody,navy);
      if(r.size()>3){CString v=r[3];v.Remove(L',');double amount=std::max(0.0,_wtof(v));
       rect(barX,y+dpi*10/100,barW,dpi*18/100,pale);
       int bw=(int)(amount/peak*barW);if(bw>0)rect(barX,y+dpi*10/100,bw,dpi*18/100,RGB(48,111,183));
       label(GroupNumber(v)+L" 원",barX+barW+dpi/12,y,amountW,rowH,fontBody,navy,DT_RIGHT);
      }y+=rowH;
     }
     y+=dpi*20/100;
     if(y+dpi*14/10>h-margin-dpi/2){footer();if(EndPage(dc)<=0||!start())ok=false;}
     if(ok){
      label(L"지역별 매출 상세",margin,y,usable,dpi/3,fontHead,navy);y+=dpi*40/100;
      const int widths[4]={usable*18/100,usable*23/100,usable*23/100,usable-usable*18/100-2*(usable*23/100)};
      const wchar_t* titles[]={L"지역",L"주문 건수",L"판매 수량",L"매출액 (원)"};
      auto headerRegion=[&](){rect(margin,y,usable,rowH,navy);int x=margin;
       for(int c=0;c<4;++c){label(titles[c],x+dpi/12,y,widths[c]-dpi/6,rowH,fontHead,RGB(255,255,255),c==0?DT_LEFT:DT_RIGHT);x+=widths[c];}y+=rowH;};
      headerRegion();long long totals[3]={};
      for(size_t i=0;i<regions.size();++i){
       if(y+rowH>h-margin-dpi/2){footer();if(EndPage(dc)<=0||!start())ok=false;if(!ok)break;headerRegion();}
       if(i%2==0)rect(margin,y,usable,rowH,RGB(247,249,252));int x=margin;
       for(int c=0;c<4;++c){CString v=c<(int)regions[i].size()?regions[i][c]:CString(L"");
        if(c>0){CString raw=v;raw.Remove(L',');if(!raw.IsEmpty()){CString rounded=GroupNumber(raw);rounded.Remove(L',');totals[c-1]+=_wtoi64(rounded);v=GroupNumber(raw);}}
        label(v,x+dpi/12,y,widths[c]-dpi/6,rowH,fontBody,navy,c==0?DT_LEFT:DT_RIGHT);x+=widths[c];
       }y+=rowH;
      }
      if(regionPicker.GetCurSel()==0 && ok && !regions.empty()){
       if(y+rowH>h-margin-dpi/2){footer();if(EndPage(dc)<=0||!start())ok=false;}
       if(ok){rect(margin,y,usable,rowH,pale);CString v[4]={L"전체 합계",L"",L"",L""};
        for(int c=1;c<4;++c){v[c].Format(L"%lld",totals[c-1]);v[c]=GroupNumber(v[c]);}
        int x=margin;for(int c=0;c<4;++c){label(v[c],x+dpi/12,y,widths[c]-dpi/6,rowH,fontHead,navy,c==0?DT_LEFT:DT_RIGHT);x+=widths[c];}y+=rowH;
       }
      }y+=dpi*18/100;
     }
    }
   }
   CString section;switch(tabs.GetCurSel()){case 0:section=L"기간별 매출 내역";break;case 1:section=L"상품별 매출 내역";break;case 2:section=L"주문 상태 현황";break;case 3:section=L"출고 및 분류 오류 현황";break;default:section=L"지역별 매출 내역";break;}
   label(section,margin,y,usable,dpi/3,fontHead,navy);y+=dpi*42/100;
   const int cols=(int)headers.size();if(cols>0){
    std::vector<int> widths(cols,usable/cols);if(cols>=3){widths[0]=usable*34/100;int rem=usable-widths[0];for(int c=1;c<cols;++c)widths[c]=rem/(cols-1);widths[cols-1]=usable-widths[0]-(cols-2)*widths[1];}
    auto tableHead=[&](){rect(margin,y,usable,rowH,navy);int x=margin;for(int c=0;c<cols;++c){label(headers[c],x+dpi/12,y,widths[c]-dpi/6,rowH,fontHead,RGB(255,255,255),c==0?DT_LEFT:DT_RIGHT);x+=widths[c];}y+=rowH;};
    tableHead();
    for(size_t r=0;r<data.size();++r){if(y+rowH>h-margin-dpi/2){footer();if(EndPage(dc)<=0||!start()){ok=false;break;}label(section+L" (계속)",margin,y,usable,dpi/3,fontHead,navy);y+=dpi*42/100;tableHead();}
     if(r%2==0)rect(margin,y,usable,rowH,RGB(247,249,252));int x=margin;
     for(int c=0;c<cols;++c){CString value=c<(int)data[r].size()?data[r][c]:CString(L"");if(c>0)value=GroupNumber(value);label(value,x+dpi/12,y,widths[c]-dpi/6,rowH,fontBody,navy,c==0?DT_LEFT:DT_RIGHT);x+=widths[c];}rect(margin,y+rowH-1,usable,1,line);y+=rowH;
    }
   }
   if(ok){footer();if(EndPage(dc)<=0)ok=false;}
  }
  if(ok){if(EndDoc(dc)<=0)ok=false;}else AbortDoc(dc);
  DeleteObject(fontTitle);DeleteObject(fontHead);DeleteObject(fontBody);DeleteDC(dc);
  if(!ok && error.IsEmpty())error=L"PDF 저장 중 인쇄 오류가 발생했습니다.";return ok;
 }
 void ExportPdfFile(){
  if(data.empty()){AfxMessageBox(L"조회할 기간과 지역을 선택한 후 조회해주세요.");return;}
  CFileDialog dlg(FALSE,L"pdf",L"Settlement.pdf",OFN_OVERWRITEPROMPT,L"PDF (*.pdf)|*.pdf||",this);
  if(dlg.DoModal()!=IDOK)return;
  CString path=dlg.GetPathName(),error;
  if(!ExportPdf(path,error)){AfxMessageBox(error.IsEmpty()?CString(L"PDF 저장 실패"):error);return;}
  HINSTANCE opened=ShellExecuteW(m_hWnd,L"open",path,nullptr,nullptr,SW_SHOWNORMAL);
  if(reinterpret_cast<INT_PTR>(opened)<=32)AfxMessageBox(L"PDF 파일은 저장되었지만 자동으로 열지 못했습니다.\n저장 위치: "+path);
 }
 afx_msg int OnCreate(LPCREATESTRUCT cs){if(CFrameWnd::OnCreate(cs)==-1)return -1;
 cardBrush.CreateSolidBrush(RGB(239,246,251));
 pageBrush.CreateSolidBrush(RGB(255,255,255));
 uiFont.CreateFontW(-15,0,0,0,FW_NORMAL,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,UiFont::Family());
 uiBold.CreateFontW(-18,0,0,0,FW_SEMIBOLD,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,UiFont::Family());
 uiKpi.CreateFontW(-24,0,0,0,FW_BOLD,0,0,0,DEFAULT_CHARSET,0,0,CLEARTYPE_QUALITY,0,UiFont::Family());CFont* f=&uiFont;
 brand.Create(L"MOBLE KURLY  /  SETTLEMENT",WS_CHILD|WS_VISIBLE,CRect(28,18,750,44),this);brand.SetFont(&uiBold);
 subtitle.Create(L"매출 결산 대시보드",WS_CHILD|WS_VISIBLE,CRect(28,52,750,78),this);subtitle.SetFont(f);
 periodLabel.Create(L"조회 기간 및 배송 지역",WS_CHILD|WS_VISIBLE,CRect(28,116,650,142),this);periodLabel.SetFont(&uiBold);
 period.Create(WS_CHILD|WS_VISIBLE|CBS_DROPDOWNLIST,CRect(28,150,148,350),this,ID_PERIOD);period.AddString(L"일별");period.AddString(L"월별");period.AddString(L"연별");period.SetCurSel(1);period.SetFont(f);
 datePicker.Create(WS_CHILD|WS_VISIBLE|DTS_SHORTDATEFORMAT,CRect(160,150,310,185),this,ID_DATE);datePicker.SetFont(f);
 yearPicker.Create(WS_CHILD|CBS_DROPDOWNLIST|WS_VSCROLL,CRect(160,150,232,440),this,ID_YEAR);yearPicker.SetFont(f);
 monthPicker.Create(WS_CHILD|CBS_DROPDOWNLIST|WS_VSCROLL,CRect(238,150,310,440),this,ID_MONTH);monthPicker.SetFont(f);
 CTime now=CTime::GetCurrentTime();for(int yy=now.GetYear()+5;yy>=2020;--yy){CString v;v.Format(L"%04d",yy);int index=yearPicker.AddString(v);if(yy==now.GetYear())yearPicker.SetCurSel(index);}
 for(int mm=1;mm<=12;++mm){CString v;v.Format(L"%02d",mm);monthPicker.AddString(v);}monthPicker.SetCurSel(now.GetMonth()-1);
 UpdateDateControls();
 regionPicker.Create(WS_CHILD|WS_VISIBLE|CBS_DROPDOWNLIST|WS_VSCROLL,CRect(326,150,436,390),this,ID_REGION);
 regionPicker.SetFont(f);regionPicker.AddString(L"전체 지역");regionPicker.AddString(L"서울");regionPicker.AddString(L"경기");regionPicker.AddString(L"충청");regionPicker.SetCurSel(0);
 refresh.Create(L"DB 연결",WS_CHILD|WS_VISIBLE|BS_OWNERDRAW,CRect(448,149,562,185),this,ID_REFRESH);refresh.SetFont(f);
 html.primary=true;
 html.Create(L"PDF 저장",WS_CHILD|WS_VISIBLE|BS_OWNERDRAW,CRect(720,149,858,185),this,ID_HTML);html.SetFont(f);
 reportLabel.Create(L"결산 핵심 지표",WS_CHILD|WS_VISIBLE,CRect(28,224,450,252),this);reportLabel.SetFont(&uiBold);
 summary.Create(L"DB 연결 후 실제 매출 데이터를 조회할 수 있습니다.",WS_CHILD|WS_VISIBLE,CRect(28,260,1000,288),this);summary.SetFont(f);
 kpiOrders.Create(L"-",WS_CHILD|WS_VISIBLE,CRect(42,314,245,378),this);kpiOrders.SetFont(&uiKpi);kpiOrderTitle.Create(L"주문 건수",WS_CHILD|WS_VISIBLE,CRect(0,0,100,25),this);kpiOrderTitle.SetFont(&uiFont);
 kpiQuantity.Create(L"-",WS_CHILD|WS_VISIBLE,CRect(285,314,485,378),this);kpiQuantity.SetFont(&uiKpi);kpiQuantityTitle.Create(L"판매 수량",WS_CHILD|WS_VISIBLE,CRect(0,0,100,25),this);kpiQuantityTitle.SetFont(&uiFont);
 kpiRevenue.Create(L"-",WS_CHILD|WS_VISIBLE,CRect(530,314,745,378),this);kpiRevenue.SetFont(&uiKpi);kpiRevenueTitle.Create(L"총 매출액",WS_CHILD|WS_VISIBLE,CRect(0,0,100,25),this);kpiRevenueTitle.SetFont(&uiFont);
 kpiErrors.Create(L"-",WS_CHILD|WS_VISIBLE,CRect(770,314,985,378),this);kpiErrors.SetFont(&uiKpi);kpiErrorsTitle.Create(L"분류 오류",WS_CHILD|WS_VISIBLE,CRect(0,0,100,25),this);kpiErrorsTitle.SetFont(&uiFont);
 // CWnd needs a registered window class. Passing nullptr can trigger an MFC assertion.
 const CString graphClass=AfxRegisterWndClass(CS_HREDRAW|CS_VREDRAW,::LoadCursor(nullptr,IDC_ARROW),(HBRUSH)(COLOR_WINDOW+1),nullptr);
 if(graphClass.IsEmpty() || !graph.Create(graphClass,L"",WS_CHILD|WS_VISIBLE,CRect(28,414,1000,620),this,110)){
  AfxMessageBox(L"매출 그래프를 표시하지 못했습니다.");return -1;
 }
 tabs.Create(WS_CHILD|WS_VISIBLE|TCS_TABS,CRect(28,640,1000,678),this,ID_TABS);tabs.SetFont(f);TCITEMW item={};item.mask=TCIF_TEXT;const wchar_t* names[]={L"기간별 매출",L"상품별 매출",L"주문 상태",L"출고 / 오류",L"지역별 매출"};for(int i=0;i<5;++i){item.pszText=(LPWSTR)names[i];tabs.InsertItem(i,&item);}
 list.Create(WS_CHILD|WS_VISIBLE|LVS_REPORT|LVS_SHOWSELALWAYS,CRect(28,680,1000,825),this,ID_LIST);list.SetExtendedStyle(LVS_EX_FULLROWSELECT|LVS_EX_DOUBLEBUFFER);list.SetFont(f);
 list.SetBkColor(RGB(255,255,255));list.SetTextBkColor(RGB(255,255,255));list.SetTextColor(RGB(37,51,67));
 status.Create(L"연결 대기  |  DB 읽기 전용",WS_CHILD|WS_VISIBLE,CRect(28,830,1000,856),this);status.SetFont(f);
 summary.ModifyStyle(0,SS_ENDELLIPSIS|SS_NOPREFIX);
 status.ModifyStyle(0,SS_ENDELLIPSIS|SS_NOPREFIX);
 wchar_t exe[MAX_PATH]={};GetModuleFileNameW(nullptr,exe,MAX_PATH);CString path(exe);ini=path.Left(path.ReverseFind(L'\\')+1)+L"config.ini";
 if(embedded_){
  brand.SetWindowTextW(L"매출 및 출고 결산");
  subtitle.SetWindowTextW(L"기간별 결산 · PDF 저장");
  refresh.SetWindowTextW(L"조회 / 갱신");
  html.MoveWindow(630,149,142,36);
  CRect current;GetClientRect(&current);
  OnSize(SIZE_RESTORED,current.Width(),current.Height());
  OnRefresh();
 }
 if(compact_){
  subtitle.SetWindowTextW(L"작업 결산 - 주문 건수 / 분류 오류");
  html.ShowWindow(SW_HIDE); kpiQuantity.ShowWindow(SW_HIDE);kpiQuantityTitle.ShowWindow(SW_HIDE);
  kpiRevenue.ShowWindow(SW_HIDE);kpiRevenueTitle.ShowWindow(SW_HIDE);
  graph.ShowWindow(SW_HIDE);tabs.ShowWindow(SW_HIDE);list.ShowWindow(SW_HIDE);
  reportLabel.SetWindowTextW(L"주문 및 분류 오류 현황");
 }
 return 0;}
 afx_msg BOOL OnEraseBkgnd(CDC* dc){CRect r;GetClientRect(&r);
 if(embedded_){
  // Paint the embedded page and KPI backgrounds only; the child controls
  // use opaque matching brushes so text never picks up repainted pixels.
  dc->FillSolidRect(&r, RGB(255,255,255));
  CRect kpiArea; kpiOrders.GetWindowRect(&kpiArea); ScreenToClient(&kpiArea);
  CRect labelArea;
  CStatic* valueCtrls[]={&kpiOrders,&kpiQuantity,&kpiRevenue,&kpiErrors};
  CStatic* labelCtrls[]={&kpiOrderTitle,&kpiQuantityTitle,&kpiRevenueTitle,&kpiErrorsTitle};
  for(int i=0;i<4;++i){
   if(!::IsWindow(labelCtrls[i]->GetSafeHwnd()))continue;
   labelCtrls[i]->GetWindowRect(&labelArea);ScreenToClient(&labelArea);
   valueCtrls[i]->GetWindowRect(&kpiArea);ScreenToClient(&kpiArea);
   CRect cardRect(std::min(labelArea.left,kpiArea.left)-5,labelArea.top-5,
                  std::max(labelArea.right,kpiArea.right)+5,kpiArea.bottom+5);
   dc->FillSolidRect(&cardRect,RGB(239,246,251));
  }
  return TRUE;
 }dc->FillSolidRect(&r,RGB(246,248,250));dc->FillSolidRect(0,0,r.Width(),95,RGB(19,55,91));dc->FillSolidRect(16,104,r.Width()-32,96,RGB(255,255,255));dc->FillSolidRect(16,212,r.Width()-32,190,RGB(255,255,255));int usable=std::max(400,r.Width()-56),gap=14,card=(usable-gap*3)/4;if(compact_){card=(usable-24)/2;for(int i=0;i<2;++i){int x=28+i*(card+24);dc->FillSolidRect(x,300,card,90,RGB(239,246,251));dc->FillSolidRect(x,300,4,90,RGB(32,120,180));}}else{for(int i=0;i<4;++i){int x=28+i*(card+gap);dc->FillSolidRect(x,300,card,90,RGB(239,246,251));dc->FillSolidRect(x,300,4,90,RGB(32,120,180));}}dc->FillSolidRect(16,406,r.Width()-32,220,RGB(255,255,255));dc->FillSolidRect(16,632,r.Width()-32,std::max(180,r.Height()-680),RGB(255,255,255));return TRUE;}
 afx_msg HBRUSH OnCtlColor(CDC* dc,CWnd* wnd,UINT type){
  if(type==CTLCOLOR_STATIC){
   HWND target=wnd->GetSafeHwnd();
   const bool isKpi=target==kpiOrders.GetSafeHwnd()||target==kpiQuantity.GetSafeHwnd()||
    target==kpiRevenue.GetSafeHwnd()||target==kpiErrors.GetSafeHwnd()||
    target==kpiOrderTitle.GetSafeHwnd()||target==kpiQuantityTitle.GetSafeHwnd()||
    target==kpiRevenueTitle.GetSafeHwnd()||target==kpiErrorsTitle.GetSafeHwnd();
   dc->SetBkMode(OPAQUE);
   if(isKpi){
    dc->SetBkColor(RGB(239,246,251));dc->SetTextColor(RGB(37,51,67));
    return (HBRUSH)cardBrush.GetSafeHandle();
   }
   if(embedded_){
    // Returning NULL_BRUSH with transparent text caused partially repainted
    // labels and ghosting on the admin tab when resized/refreshed.
    dc->SetBkColor(RGB(255,255,255));dc->SetTextColor(RGB(37,51,67));
    return (HBRUSH)pageBrush.GetSafeHandle();
   }
   if(target==brand.GetSafeHwnd()||target==subtitle.GetSafeHwnd()){
    dc->SetBkColor(RGB(19,55,91));
    dc->SetTextColor(target==brand.GetSafeHwnd()?RGB(255,255,255):RGB(202,217,237));
    return (HBRUSH)GetStockObject(NULL_BRUSH);
   }
   if(target==summary.GetSafeHwnd()){
    dc->SetBkColor(RGB(255,255,255));dc->SetTextColor(RGB(37,51,67));
    return (HBRUSH)pageBrush.GetSafeHandle();
   }
   dc->SetBkMode(TRANSPARENT);dc->SetTextColor(RGB(37,51,67));
   return (HBRUSH)GetStockObject(NULL_BRUSH);
  }
  return CFrameWnd::OnCtlColor(dc,wnd,type);
 }
 afx_msg void OnSize(UINT t,int w,int h){CFrameWnd::OnSize(t,w,h);if(!::IsWindow(list.m_hWnd))return;
 if(embedded_){
  // Reflow native controls inside the report panel without changing their IDs.
  const int pad=16,inner=std::max(0,w-2*pad);
  if(inner<420 || h<480)return;
  const bool narrow=inner<700;
  brand.MoveWindow(pad,8,inner,28);
  subtitle.MoveWindow(pad,38,inner,22);
  periodLabel.MoveWindow(pad,70,inner,24);
  period.MoveWindow(pad,102,100,220);
  datePicker.MoveWindow(pad+110,102,138,32);
  yearPicker.MoveWindow(pad+110,102,66,220);
  monthPicker.MoveWindow(pad+182,102,66,220);
  regionPicker.MoveWindow(pad+258,102,116,220);
  if(narrow){
   refresh.MoveWindow(pad,142,116,34);
   html.MoveWindow(pad+126,142,134,34);
  }else{
   refresh.MoveWindow(pad+388,101,116,34);
   html.MoveWindow(w-pad-134,101,134,34);
  }
  const int reportY=narrow?186:148;
  reportLabel.MoveWindow(pad,reportY,inner,24);
  const int kpiTitleY=reportY+35;
  const int gap=12,columns=narrow?2:4;
  const int card=std::max(80,(inner-(columns-1)*gap)/columns);
  CStatic* kpis[]={&kpiOrders,&kpiQuantity,&kpiRevenue,&kpiErrors};
  CStatic* titles[]={&kpiOrderTitle,&kpiQuantityTitle,&kpiRevenueTitle,&kpiErrorsTitle};
  for(int i=0;i<4;++i){
   const int column=i%columns,row=i/columns;
   const int x=pad+column*(card+gap)+9,y=kpiTitleY+row*74;
   titles[i]->MoveWindow(x,y,card-18,23);
   kpis[i]->MoveWindow(x,y+24,card-18,36);
  }
  const int summaryY=kpiTitleY+(narrow?74:0)+69;
  summary.MoveWindow(pad,summaryY,inner,24);
  const int graphY=summaryY+30;
  const int graphH=std::max(50,std::min(210,(h-graphY-112)/2));
  graph.MoveWindow(pad,graphY,inner,graphH);
  const int tabsY=graphY+graphH+10;
  tabs.MoveWindow(pad,tabsY,inner,32);
  const int listY=tabsY+35;
  const int statusY=h-30;
  list.MoveWindow(pad,listY,inner,std::max(24,statusY-listY-8));
  status.MoveWindow(pad,statusY,inner,24);
  FitListColumns();
  Invalidate(FALSE);return;
 }
 if(compact_){
  int content=std::max(400,w-56);
  summary.MoveWindow(28,260,content,26);
  const int gap=24, card=(content-gap)/2;
  kpiOrderTitle.MoveWindow(46,318,card-32,27);
  kpiOrders.MoveWindow(46,350,card-32,36);
  kpiErrorsTitle.MoveWindow(46+card+gap,318,card-32,27);
  kpiErrors.MoveWindow(46+card+gap,350,card-32,36);
  status.MoveWindow(28,std::max(420,h-55),content,26);return;
 }
 int content=std::max(400,w-56);summary.MoveWindow(28,260,content,26,TRUE);
 if(embedded_) html.MoveWindow(std::max(570,w-180),149,142,36);int gap=14,card=(content-gap*3)/4;CStatic* kpis[]={&kpiOrders,&kpiQuantity,&kpiRevenue,&kpiErrors};CStatic* titles[]={&kpiOrderTitle,&kpiQuantityTitle,&kpiRevenueTitle,&kpiErrorsTitle};for(int i=0;i<4;++i){int x=42+i*(card+gap);titles[i]->MoveWindow(x,307,card-26,25);kpis[i]->MoveWindow(x,341,card-26,39);}graph.MoveWindow(28,414,content,205);tabs.MoveWindow(28,640,content,38);list.MoveWindow(28,681,content,std::max(95,h-735));status.MoveWindow(28,std::max(785,h-44),content,25);FitListColumns();Invalidate(TRUE);}
 afx_msg void OnRefresh(){if(!connected){CString err;if(!db.Connect(ini,err)){AfxMessageBox(L"결산 서버에 연결하지 못했습니다.\n\n"+err+L"");return;}connected=true;}Reload();}
afx_msg void OnHtml(){ExportPdfFile();}
 void UpdateDateControls(){int sel=period.GetCurSel();if(!::IsWindow(datePicker.GetSafeHwnd()))return;
 datePicker.ShowWindow(sel==0?SW_SHOW:SW_HIDE);
 yearPicker.ShowWindow(sel!=0?SW_SHOW:SW_HIDE);
 monthPicker.ShowWindow(sel==1?SW_SHOW:SW_HIDE);
 }
 afx_msg void OnPeriod(){UpdateDateControls();Reload();}
 afx_msg void OnYearMonth(){Reload();}afx_msg void OnDate(NMHDR*,LRESULT* r){Reload();*r=0;}afx_msg void OnTab(NMHDR*,LRESULT* r){Reload();*r=0;}
 DECLARE_MESSAGE_MAP()
};
BEGIN_MESSAGE_MAP(SettlementFrame,CFrameWnd)
 ON_WM_CREATE() ON_WM_SIZE() ON_WM_ERASEBKGND() ON_WM_CTLCOLOR() ON_BN_CLICKED(ID_REFRESH,OnRefresh) ON_BN_CLICKED(ID_HTML,OnHtml)
 ON_CBN_SELCHANGE(ID_REGION,OnYearMonth) ON_CBN_SELCHANGE(ID_PERIOD,OnPeriod) ON_CBN_SELCHANGE(ID_YEAR,OnYearMonth) ON_CBN_SELCHANGE(ID_MONTH,OnYearMonth) ON_NOTIFY(DTN_DATETIMECHANGE,ID_DATE,OnDate) ON_NOTIFY(TCN_SELCHANGE,ID_TABS,OnTab)
END_MESSAGE_MAP()

void OpenIntegratedSettlement(bool compact){
 auto* frame=new SettlementFrame(compact);
 if(!::IsWindow(frame->GetSafeHwnd())){delete frame;AfxMessageBox(L"결산 화면을 열지 못했습니다.");return;}
 frame->ShowWindow(SW_SHOW);frame->UpdateWindow();
}

// Child-hosted version reuses the complete original read-only DB queries,
// period/region filters, tabular details, graph and Microsoft Print to PDF exporter.
CWnd* CreateEmbeddedSettlement(CWnd* parent, const CRect& area){
 auto* frame=new SettlementFrame(false,parent,area);
 if(!::IsWindow(frame->GetSafeHwnd())){delete frame;AfxMessageBox(L"관리자 결산 화면을 열지 못했습니다.");return nullptr;}
 frame->ShowWindow(SW_SHOW);frame->UpdateWindow();
 return frame;
}
