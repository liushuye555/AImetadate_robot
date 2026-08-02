#include <QApplication>
#include <QIcon>
#include <QLabel>
#include <QMessageBox>
#include "app/SingleInstance.h"
#include "ui/MainWindow.h"
#include "ui/Strings.h"
#include "ui/theme/ThemeManager.h"

static QWidget *makePlaceholder(const char *key, QWidget *parent) {
    auto *label = new QLabel(Strings::zh(QString::fromLatin1(key)), parent);
    label->setAlignment(Qt::AlignCenter);
    return label;
}

static QWidget *makeOverview(QWidget *parent) { return makePlaceholder("overview", parent); }
static QWidget *makeSettings(QWidget *parent) { return makePlaceholder("settings", parent); }
static QWidget *makeLogs(QWidget *parent) { return makePlaceholder("logs", parent); }
static QWidget *makeReports(QWidget *parent) { return makePlaceholder("reports", parent); }

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    app.setApplicationName("QQ OneBot 管理器");
    app.setWindowIcon(QIcon(":/icons/app.svg"));

    SingleInstance single("qq-onebot-manager-qt");
    if (!single.tryLock()) {
        QMessageBox::information(nullptr, "QQ OneBot 管理器", "管理器已在运行。");
        return 0;
    }

    ThemeManager::apply(&app, ThemeManager::Theme::Light);

    const QVector<PageDef> pages = {
        {"overview", "overview", makeOverview},
        {"settings", "settings", makeSettings},
        {"logs", "logs", makeLogs},
        {"reports", "reports", makeReports},
    };
    MainWindow window(pages);
    window.show();
    return app.exec();
}
