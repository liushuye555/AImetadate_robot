#include <QApplication>
#include <QIcon>
#include <QMessageBox>
#include <QWidget>
#include "app/SingleInstance.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    app.setApplicationName("QQ OneBot 管理器");
    app.setWindowIcon(QIcon(":/icons/app.svg"));

    SingleInstance single("qq-onebot-manager-qt");
    if (!single.tryLock()) {
        QMessageBox::information(nullptr, "QQ OneBot 管理器", "管理器已在运行。");
        return 0;
    }

    QWidget window;
    window.setWindowTitle("QQ OneBot 管理器");
    window.resize(960, 640);
    window.show();
    return app.exec();
}
