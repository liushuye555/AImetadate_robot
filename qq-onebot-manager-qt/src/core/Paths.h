#pragma once
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QString>
#include <QUrl>

class Paths {
public:
    static QString repoRoot() {
        QDir dir(QCoreApplication::applicationDirPath());
        while (!dir.exists("config.yaml")) {
            if (!dir.cdUp()) break;
        }
        return dir.absolutePath();
    }
    static QString statusFile() { return repoRoot() + "/run/status.json"; }
    static QString manualStopFile() { return repoRoot() + "/run/manual-stop"; }
    static QUrl reportUrl(const QString &relative) {
        // Only explicit HTML fragments are navigation; '#' in ordinary names stays literal.
        const qsizetype fragmentAt = relative.indexOf(QStringLiteral(".html#"));
        const QString path = fragmentAt < 0 ? relative : relative.left(fragmentAt + 5);
        // Gallery filters are URL queries; '#' in image filenames remains literal.
        const qsizetype queryAt = path.indexOf(QStringLiteral("gallery.html?"));
        const QString local = queryAt < 0 ? path : path.left(queryAt + 12);
        QUrl result = QUrl::fromLocalFile(repoRoot() + "/" + local);
        if (queryAt >= 0) result.setQuery(path.mid(queryAt + 13));
        if (fragmentAt >= 0) result.setFragment(relative.mid(fragmentAt + 6));
        return result;
    }
    static QString pythonExe() {
        const QString candidate = repoRoot() + "/.venv/Scripts/python.exe";
        return QFileInfo::exists(candidate) ? candidate : "python";
    }
};
