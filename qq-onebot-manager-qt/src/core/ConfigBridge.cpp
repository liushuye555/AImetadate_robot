#include "ConfigBridge.h"
#include "Paths.h"
#include <QJsonDocument>

ConfigBridge::ConfigBridge(QObject *parent) : QObject(parent) {
    connect(&m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
        const QString output = QString::fromUtf8(m_proc.readAllStandardOutput());
        if (m_mode == Mode::Fetch) {
            QJsonParseError err;
            const QJsonDocument doc = QJsonDocument::fromJson(output.toUtf8(), &err);
            emit schemaLoaded(code == 0 && err.error == QJsonParseError::NoError, doc.toVariant());
        } else {
            emit saved(code == 0, output.trimmed());
        }
    });
}

void ConfigBridge::fetch() {
    m_mode = Mode::Fetch;
    runArgs({"-m", "qq_onebot_whitelist.config_bridge", "schema", "--config",
             Paths::repoRoot() + "/config.yaml"});
}

void ConfigBridge::save(const QJsonObject &patch) {
    m_mode = Mode::Save;
    runArgs({"-m", "qq_onebot_whitelist.config_bridge", "patch", "--config",
             Paths::repoRoot() + "/config.yaml",
             "--json",
             QString::fromUtf8(QJsonDocument(nestDottedPatch(patch)).toJson(QJsonDocument::Compact))});
}

void ConfigBridge::runArgs(const QStringList &args) {
    if (m_proc.state() != QProcess::NotRunning) return;
    m_proc.setProgram(Paths::pythonExe());
    m_proc.setArguments(args);
    m_proc.setWorkingDirectory(Paths::repoRoot());
    m_proc.start();
}

static void insertNested(QJsonObject &target, const QStringList &parts, int index, const QJsonValue &value) {
    if (index == parts.size() - 1) {
        target.insert(parts[index], value);
        return;
    }
    QJsonObject child = target.value(parts[index]).toObject();
    insertNested(child, parts, index + 1, value);
    target.insert(parts[index], child);
}

QJsonObject nestDottedPatch(const QJsonObject &flat) {
    QJsonObject nested;
    for (auto it = flat.constBegin(); it != flat.constEnd(); ++it)
        insertNested(nested, it.key().split('.'), 0, it.value());
    return nested;
}
