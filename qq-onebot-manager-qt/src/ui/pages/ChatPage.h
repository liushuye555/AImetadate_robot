#pragma once
#include <QJsonObject>
#include <QWidget>

class QCheckBox;
class QLabel;
class QPlainTextEdit;
class QPushButton;
class QSpinBox;

class ChatPage : public QWidget {
    Q_OBJECT
public:
    explicit ChatPage(QWidget *parent = nullptr);
    void setSchema(const QVariant &schema);
    void setSavedMessage(const QString &text);
signals:
    void saveRequested(QJsonObject patch);
private:
    void markDirty();
    QCheckBox *m_enabled = nullptr;
    QPlainTextEdit *m_persona = nullptr;
    QSpinBox *m_memoryTurns = nullptr;
    QSpinBox *m_adminMemoryTurns = nullptr;
    QSpinBox *m_cooldown = nullptr;
    QPushButton *m_save = nullptr;
    QLabel *m_message = nullptr;
    bool m_schemaLoaded = false;
};
