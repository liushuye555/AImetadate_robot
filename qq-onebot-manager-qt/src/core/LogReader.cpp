#include "LogReader.h"

LogReader::LogReader(QStringList paths, QObject *parent)
    : QObject(parent), m_paths(paths) {
    m_timer.setInterval(1000);
    connect(&m_timer, &QTimer::timeout, this, &LogReader::poll);
    m_timer.start();
}

void LogReader::setActive(int index) {
    m_active = index;
    if (m_file.isOpen()) m_file.close();
    m_pos = 0;
    if (index >= 0 && index < m_paths.size()) {
        m_file.setFileName(m_paths[index]);
        if (m_file.open(QIODevice::ReadOnly))
            m_pos = m_file.size(); // 只读新增内容
    }
}

void LogReader::poll() {
    if (!m_file.isOpen()) return;
    const qint64 size = m_file.size();
    if (size < m_pos) m_pos = 0;
    if (size == m_pos) return;
    m_file.seek(m_pos);
    emit newChunk(QString::fromUtf8(m_file.read(size - m_pos)));
    m_pos = m_file.size();
}
