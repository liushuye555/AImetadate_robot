#include <QCoreApplication>
#include <QDir>
#include <QImage>
#include <QPainter>
#include <QSvgRenderer>
#include <QDebug>
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    if (argc != 2) return 1;
    QDir icons(QString::fromLocal8Bit(argv[1]));
    QStringList names = {"app"};
    names += icons.entryList({"nav-*.svg", "card-*.svg", "action-*.svg"}, QDir::Files);
    for (QString name : names) {
        if (!name.endsWith(".svg")) name += ".svg";
        QSvgRenderer renderer(icons.filePath(name));
        if (!renderer.isValid()) { qCritical() << "Invalid icon:" << name; return 2; }
        QImage image(256, 256, QImage::Format_ARGB32_Premultiplied);
        image.fill(Qt::transparent);
        {
            QPainter painter(&image);
            painter.setRenderHint(QPainter::Antialiasing);
            painter.setRenderHint(QPainter::SmoothPixmapTransform);
            renderer.render(&painter);
        }
        const QString output = icons.filePath(name.left(name.size() - 4) + ".png");
        if (!image.save(output)) return 3;
    }
    qInfo() << "Exported" << names.size() << "smooth portrait PNG icons.";
    return 0;
}
