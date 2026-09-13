#pragma once
#include <QObject>
#include <QPixmap>
#include <functional>

class QListWidget;
class QNetworkAccessManager;

// QQ 头像缓存：群头像/用户头像异步拉取 + 磁盘缓存（data/panel-cache/avatars）。
// 列表页用它给每个群条目挂头像；网络失败时保留占位图，不影响功能。
class AvatarCache : public QObject {
    Q_OBJECT
public:
    static AvatarCache &instance();
    // 给列表里 data(UserRole)==groupId 的条目设置占位头像，并在拉取成功后回填真实头像
    static void decorateGroup(QListWidget *list, const QString &groupId, const QString &name);
    // 圆形占位图：取标识首字符，颜色由 id 哈希决定
    static QPixmap placeholder(const QString &seed, int size);
    void fetch(const QString &kind, const QString &id, std::function<void(const QPixmap &)> cb);
private:
    explicit AvatarCache(QObject *parent = nullptr);
    QString cachePath(const QString &kind, const QString &id) const;
    QNetworkAccessManager *nam();
    QNetworkAccessManager *m_nam = nullptr;
};
