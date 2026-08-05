#include "ConfigBridge.h"
#include "Paths.h"
#include <QJsonDocument>
#include <QProcessEnvironment>

ConfigBridge::ConfigBridge(QObject *parent) : QObject(parent) {
    connect(&m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
        const QString output = QString::fromUtf8(m_proc.readAllStandardOutput());
        const Mode doneMode = m_mode;
        if (doneMode == Mode::Fetch) {
            QJsonParseError err;
            const QJsonDocument doc = QJsonDocument::fromJson(output.toUtf8(), &err);
            emit schemaLoaded(code == 0 && err.error == QJsonParseError::NoError, doc.toVariant());
        } else {
            emit saved(code == 0, output.trimmed());
        }
        startNext();  // 串行执行排队中的保存/刷新，避免忙时静默丢弃
    });
}

void ConfigBridge::fetch() {
    runArgs({"-m", "qq_onebot_whitelist.config_bridge", "schema", "--config",
             Paths::repoRoot() + "/config.yaml"}, Mode::Fetch);
}

void ConfigBridge::save(const QJsonObject &patch) {
    runArgs({"-m", "qq_onebot_whitelist.config_bridge", "patch", "--config",
             Paths::repoRoot() + "/config.yaml",
             "--json",
             QString::fromUtf8(QJsonDocument(nestDottedPatch(patch)).toJson(QJsonDocument::Compact))},
            Mode::Save);
}

void ConfigBridge::saveEnv(const QJsonObject &values) {
    runArgs({"-m", "qq_onebot_whitelist.config_bridge", "env-patch", "--config",
             Paths::repoRoot() + "/config.yaml", "--json",
             QString::fromUtf8(QJsonDocument(values).toJson(QJsonDocument::Compact))},
            Mode::EnvSave);
}

void ConfigBridge::runArgs(const QStringList &args, Mode mode) {
    m_queue.enqueue({mode, args});
    startNext();
}

void ConfigBridge::startNext() {
    if (m_queue.isEmpty() || m_proc.state() != QProcess::NotRunning) return;
    const Pending op = m_queue.dequeue();
    m_mode = op.mode;
    m_proc.setProgram(Paths::pythonExe());
    m_proc.setArguments(op.args);
    m_proc.setWorkingDirectory(Paths::repoRoot());
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONUTF8", "1"); // 保证子进程输出 UTF-8，避免无控制台时按 GBK 编码导致 JSON 解析失败
    m_proc.setProcessEnvironment(env);
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
