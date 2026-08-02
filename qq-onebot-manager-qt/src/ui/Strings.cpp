#include "Strings.h"

QString Strings::get(const QString &key, const QString &lang) {
    return lang == "en-US" ? en(key) : zh(key);
}

QString Strings::zh(const QString &key) {
    if (key == "overview") return "概览";
    if (key == "settings") return "设置";
    if (key == "logs") return "日志";
    if (key == "reports") return "报告";
    if (key == "start") return "启动";
    if (key == "stop") return "停止";
    if (key == "restart") return "重启";
    if (key == "refresh") return "刷新";
    if (key == "openLogs") return "打开日志";
    if (key == "openReports") return "打开报告";
    if (key == "openConfig") return "打开配置目录";
    if (key == "importHistory") return "立即读取历史";
    if (key == "service") return "服务状态";
    if (key == "manualStop") return "已手动停止，自动重启已暂停";
    if (key == "autoRestartOn") return "自动重启：已开启";
    if (key == "autoRestartOff") return "自动重启：已关闭";
    if (key == "save") return "保存";
    if (key == "saved") return "已保存";
    if (key == "error") return "出错";
    if (key == "search") return "搜索";
    if (key == "pause") return "暂停";
    if (key == "autoScroll") return "自动滚动";
    if (key == "onlyErrors") return "只看错误";
    if (key == "language") return "语言";
    if (key == "theme") return "主题";
    if (key == "autoStart") return "开机自启";
    if (key == "notifications") return "登录提醒";
    if (key == "quit") return "退出管理器";
    if (key == "qqLogin") return "QQ 已登录";
    if (key == "qqLogout") return "QQ 已掉线";
    if (key == "running") return "运行中";
    if (key == "stopped") return "已停止";
    if (key == "preview") return "生成预览";
    if (key == "sendTest") return "发送测试日报";
    if (key == "general") return "通用";
    return key;
}

QString Strings::en(const QString &key) {
    if (key == "overview") return "Overview";
    if (key == "settings") return "Settings";
    if (key == "logs") return "Logs";
    if (key == "reports") return "Reports";
    if (key == "start") return "Start";
    if (key == "stop") return "Stop";
    if (key == "restart") return "Restart";
    if (key == "refresh") return "Refresh";
    if (key == "openLogs") return "Open logs";
    if (key == "openReports") return "Open reports";
    if (key == "openConfig") return "Open config folder";
    if (key == "importHistory") return "Import history now";
    if (key == "service") return "Service status";
    if (key == "manualStop") return "Manually stopped; auto-restart paused";
    if (key == "autoRestartOn") return "Auto-restart: on";
    if (key == "autoRestartOff") return "Auto-restart: off";
    if (key == "save") return "Save";
    if (key == "saved") return "Saved";
    if (key == "error") return "Error";
    if (key == "search") return "Search";
    if (key == "pause") return "Pause";
    if (key == "autoScroll") return "Auto-scroll";
    if (key == "onlyErrors") return "Errors only";
    if (key == "language") return "Language";
    if (key == "theme") return "Theme";
    if (key == "autoStart") return "Start with Windows";
    if (key == "notifications") return "Login notifications";
    if (key == "quit") return "Quit manager";
    if (key == "qqLogin") return "QQ logged in";
    if (key == "qqLogout") return "QQ disconnected";
    if (key == "running") return "Running";
    if (key == "stopped") return "Stopped";
    if (key == "preview") return "Generate preview";
    if (key == "sendTest") return "Send test report";
    if (key == "general") return "General";
    return key;
}
