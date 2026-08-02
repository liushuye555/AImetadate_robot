#include "AutoStart.h"
#include "Paths.h"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QStandardPaths>
#include <windows.h>
#include <shobjidl.h>

QString AutoStart::startupLinkPath() {
    return QStandardPaths::writableLocation(QStandardPaths::ApplicationsLocation)
        + "/Startup/QQ OneBot 管理器.lnk";
}

bool AutoStart::isEnabled() { return QFileInfo::exists(startupLinkPath()); }

bool AutoStart::setEnabled(bool enabled) {
    const QString link = startupLinkPath();
    if (!enabled) {
        return QFile::remove(link);
    }
    const QString target = QCoreApplication::applicationFilePath();
    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE) return false;
    IShellLinkW *shellLink = nullptr;
    hr = CoCreateInstance(CLSID_ShellLink, nullptr, CLSCTX_INPROC_SERVER,
                          IID_IShellLinkW, reinterpret_cast<void **>(&shellLink));
    if (FAILED(hr)) {
        if (hr != RPC_E_CHANGED_MODE) CoUninitialize();
        return false;
    }
    shellLink->SetPath(reinterpret_cast<LPCWSTR>(target.utf16()));
    shellLink->SetWorkingDirectory(reinterpret_cast<LPCWSTR>(Paths::repoRoot().utf16()));
    IPersistFile *persist = nullptr;
    hr = shellLink->QueryInterface(IID_IPersistFile, reinterpret_cast<void **>(&persist));
    bool ok = false;
    if (SUCCEEDED(hr)) {
        hr = persist->Save(reinterpret_cast<LPCWSTR>(link.utf16()), TRUE);
        ok = SUCCEEDED(hr);
        persist->Release();
    }
    shellLink->Release();
    if (hr != RPC_E_CHANGED_MODE) CoUninitialize();
    return ok;
}
