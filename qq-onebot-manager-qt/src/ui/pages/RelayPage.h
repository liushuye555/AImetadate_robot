#pragma once
#include <QJsonObject>
#include <QStringList>
#include <QWidget>

class QCheckBox;
class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPlainTextEdit;
class QPushButton;
class QSpinBox;

class RelayPage : public QWidget {
    Q_OBJECT
public:
    explicit RelayPage(QWidget *parent = nullptr);
    void setSchema(const QVariant &schema);
    void setGroups(const QVariantList &groups);
    void setSavedMessage(const QString &text);
signals:
    void saveRequested(QJsonObject patch);
    void groupsScanRequested();
private:
    QWidget *buildGroupBox(const QString &title, QListWidget *&list, bool withScan);
    void openGroupDialog(QListWidget *list, const QString &editId);
    QStringList groupIds(QListWidget *list) const;
    void fillGroupList(QListWidget *list, const QJsonArray &ids);
    void markDirty();
    QCheckBox *m_enabled = nullptr;
    QComboBox *m_mode = nullptr;
    QListWidget *m_groups = nullptr;
    QListWidget *m_inputGroups = nullptr;
    QListWidget *m_outputGroups = nullptr;
    QCheckBox *m_ordinary = nullptr;
    QPlainTextEdit *m_keywords = nullptr;
    QLineEdit *m_regex = nullptr;
    QCheckBox *m_aiFilter = nullptr;
    QSpinBox *m_dedupeHours = nullptr;
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
};
