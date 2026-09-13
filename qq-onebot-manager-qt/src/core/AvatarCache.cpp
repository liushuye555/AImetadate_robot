#include "AvatarCache.h"
#include "Paths.h"
#include <QDir>
#include <QFileInfo>
#include <QHash>
#include <QListWidget>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPainter>
#include <QPointer>
#include <QUrl>

namespace {
// 柔和底色盘：按 id 哈希取色，占位头像不会千篇一律
const char *kPalette[] = {"#eb2f96", "#7a5af8", "#2f6bdb", "#12a19a", "#e8890c", "#d64550"};
constexpr int kAvatarSize = 100;
}

AvatarCache &AvatarCache::instance() {
    static AvatarCache cache;
    return cache;
}

AvatarCache::AvatarCache(QObject *parent) : QObject(parent) {}

QNetworkAccessManager *AvatarCache::nam() {
    if (!m_nam) {
        m_nam = new QNetworkAccessManager(this);
    }
    return m_nam;
}

QString AvatarCache::cachePath(const QString &kind, const QString &id) const {
    return Paths::repoRoot() + "/data/panel-cache/avatars/" + kind + "-" + id + ".png";
}

QPixmap AvatarCache::placeholder(const QString &seed, int size) {
    QPixmap pm(size, size);
    pm.fill(Qt::transparent);
    const QString text = seed.trimmed().isEmpty() ? QStringLiteral("?") : seed.trimmed().left(1).toUpper();
    const uint hash = qHash(seed);
    QPainter painter(&pm);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor(kPalette[hash % (sizeof(kPalette) / sizeof(kPalette[0]))]));
    painter.drawEllipse(0, 0, size, size);
    painter.setPen(Qt::white);
    QFont font = painter.font();
    font.setPixelSize(size * 52 / 100);
    font.setBold(true);
    painter.setFont(font);
    painter.drawText(pm.rect(), Qt::AlignCenter, text);
    return pm;
}

void AvatarCache::decorateGroup(QListWidget *list, const QString &groupId, const QString &name) {
    if (!list || groupId.isEmpty()) return;
    const QPixmap placeholderPm = placeholder(groupId, 32);
    for (int i = 0; i < list->count(); ++i) {
        QListWidgetItem *item = list->item(i);
        if (item && item->data(Qt::UserRole).toString() == groupId)
            item->setIcon(placeholderPm);
    }
    // 页面销毁后 list 悬空：QPointer 保护，回调直接跳过
    QPointer<QListWidget> guard(list);
    instance().fetch("group", groupId, [guard, groupId](const QPixmap &pm) {
        if (!guard) return;
        for (int i = 0; i < guard->count(); ++i) {
            QListWidgetItem *item = guard->item(i);
            if (item && item->data(Qt::UserRole).toString() == groupId)
                item->setIcon(pm);
        }
    });
}

void AvatarCache::fetch(const QString &kind, const QString &id, std::function<void(const QPixmap &)> cb) {
    if (id.isEmpty()) return;
    const QString path = cachePath(kind, id);
    const QFileInfo info(path);
    if (info.exists() && info.size() > 0) {
        QPixmap cached;
        if (cached.load(path)) {
            cb(cached);
            return;
        }
    }
    const QUrl url = kind == QStringLiteral("user")
        ? QUrl(QStringLiteral("https://q1.qlogo.cn/g?b=qq&nk=%1&s=%2").arg(id).arg(kAvatarSize))
        : QUrl(QStringLiteral("https://p.qlogo.cn/gh/%1/%1/%2").arg(id).arg(kAvatarSize));
    QNetworkRequest request(url);
    request.setTransferTimeout(8000);
    QNetworkReply *reply = nam()->get(request);
    connect(reply, &QNetworkReply::finished, this, [this, reply, path, cb] {
        reply->deleteLater();
        if (reply->error() != QNetworkReply::NoError) return;
        QPixmap pm;
        if (!pm.loadFromData(reply->readAll())) return;
        QDir().mkpath(QFileInfo(path).absolutePath());
        pm.save(path, "PNG");
        cb(pm);
    });
}
