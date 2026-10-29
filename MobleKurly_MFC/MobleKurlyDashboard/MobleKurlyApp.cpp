#include <afxwin.h>
#include "DashboardFrame.h"
#include "LoginDialog.h"
#include "UiFont.h"

class MobleKurlyApp : public CWinApp {
public:
    BOOL InitInstance() override {
        CWinApp::InitInstance();
        // Initialize fonts and GDI+ before the login dialog paints.
        UiFont::Initialize();
        LoginDialog login;
        if (login.ShowLogin() != IDOK) return FALSE;
        auto* frame = new DashboardFrame(login.UserId(), login.DisplayName(), login.Role());
        if (!frame->GetSafeHwnd()) { delete frame; return FALSE; }
        m_pMainWnd=frame;
        frame->ShowWindow(SW_SHOW);
        frame->UpdateWindow();
        return TRUE;
    }
    int ExitInstance() override {
        UiFont::Shutdown();
        return CWinApp::ExitInstance();
    }
};
MobleKurlyApp theApp;
