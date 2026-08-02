#pragma once
#include <QWidget>

class QComboBox;
class QPlainTextEdit;
class QCheckBox;
class QLineEdit;
class LogReader;

class LogsPage : public QWidget {
    Q_OBJECT
public:
    explicit LogsPage(QWidget *parent = nullptr);
private:
    QComboBox *m_selector = nullptr;
    QPlainTextEdit *m_view = nullptr;
    QCheckBox *m_autoScroll = nullptr;
    QCheckBox *m_onlyErrors = nullptr;
    QLineEdit *m_filter = nullptr;
    LogReader *m_reader = nullptr;
    void appendChunk(const QString &text);
};
