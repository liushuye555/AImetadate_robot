#pragma once
#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QString>

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
    static QString pythonExe() {
        const QString candidate = repoRoot() + "/.venv/Scripts/python.exe";
        return QFileInfo::exists(candidate) ? candidate : "python";
    }
};
