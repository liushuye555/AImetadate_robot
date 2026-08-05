#pragma once
#include <QObject>
#include <QProcess>
#include <QJsonObject>
#include <QQueue>
#include <QStringList>
#include <QVariant>

// 把 {"a.b.c": v} 展平键转成 {"a": {"b": {"c": v}}} 嵌套结构（config_bridge patch 需要嵌套 JSON）。
QJsonObject nestDottedPatch(const QJsonObject &flat);

class ConfigBridge : public QObject {
    Q_OBJECT
public:
    explicit ConfigBridge(QObject *parent = nullptr);
    void fetch();                  // config_bridge get
    void save(const QJsonObject &patch); // config_bridge patch <json>
    void saveEnv(const QJsonObject &values); // config_bridge env-patch <json>
signals:
    void schemaLoaded(bool ok, QVariant schema);
    void saved(bool ok, QString message);
private:
    enum class Mode { Fetch, Save, EnvSave };
    struct Pending {
        Mode mode;
        QStringList args;
    };
    void runArgs(const QStringList &args, Mode mode);
    void startNext();
    QProcess m_proc;
    Mode m_mode = Mode::Fetch;
    QQueue<Pending> m_queue;
};
