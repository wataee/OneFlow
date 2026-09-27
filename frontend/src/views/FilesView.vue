<template>
  <div class="files-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Файловое хранилище</h1>
        <p class="page-subtitle">
          Загрузка документов (PDF, JPG, PNG, XLSX, XML, ZIP) с валидацией magic-байтов и soft-delete
        </p>
      </div>
      <n-button secondary :loading="loading" @click="fetchFiles">
        🔄 Обновить
      </n-button>
    </div>

    <!-- Upload Card -->
    <n-card title="Загрузка нового файла" size="small">
      <div class="upload-area">
        <input
          ref="fileInputRef"
          type="file"
          accept=".pdf,.jpg,.jpeg,.png,.xlsx,.xml,.zip"
          style="display: none"
          @change="handleFileSelected"
        />
        <n-space align="center">
          <n-button type="primary" :loading="uploading" @click="triggerFileInput">
            📁 Выбрать файл для загрузки
          </n-button>
          <span class="upload-hint">
            Разрешены: PDF, JPG, PNG, XLSX, XML, ZIP (макс. 25 MB). Контент валидируется по сигнатурам.
          </span>
        </n-space>
      </div>

      <n-alert v-if="uploadError" type="error" style="margin-top: 12px" closable @close="uploadError = ''">
        {{ uploadError }}
      </n-alert>
      <n-alert v-if="uploadSuccess" type="success" style="margin-top: 12px" closable @close="uploadSuccess = ''">
        {{ uploadSuccess }}
      </n-alert>
    </n-card>

    <!-- Files Table -->
    <n-card title="Файлы организации" style="margin-top: 24px" size="small">
      <n-space style="margin-bottom: 16px" align="center">
        <n-checkbox v-model:checked="includeDeleted" @update:checked="fetchFiles">
          Показывать удаленные файлы (Soft-Deleted)
        </n-checkbox>
      </n-space>

      <n-data-table
        :loading="loading"
        :columns="columns"
        :data="files"
        :bordered="false"
      />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h } from 'vue';
import {
  NCard,
  NSpace,
  NButton,
  NAlert,
  NCheckbox,
  NDataTable,
  NTag,
  DataTableColumns,
} from 'naive-ui';
import { apiClient } from '@/api/client';
import type { FileMetadata, PaginatedResponse } from '@/types';

const loading = ref(false);
const uploading = ref(false);
const uploadError = ref('');
const uploadSuccess = ref('');
const includeDeleted = ref(false);
const files = ref<FileMetadata[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);

const triggerFileInput = () => {
  fileInputRef.value?.click();
};

const handleFileSelected = async (event: Event) => {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;

  uploadError.value = '';
  uploadSuccess.value = '';
  uploading.value = true;

  try {
    const formData = new FormData();
    formData.append('file', file);

    const resp = await apiClient.post<FileMetadata>('/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    uploadSuccess.value = `Файл "${resp.data.filename}" успешно загружен и верифицирован!`;
    fetchFiles();
  } catch (err: any) {
    uploadError.value = err.message || 'Ошибка загрузки файла';
  } finally {
    uploading.value = false;
    if (fileInputRef.value) fileInputRef.value.value = '';
  }
};

const fetchFiles = async () => {
  loading.value = true;
  try {
    const resp = await apiClient.get<PaginatedResponse<FileMetadata>>('/files/', {
      params: { include_deleted: includeDeleted.value },
    });
    files.value = resp.data.items;
  } finally {
    loading.value = false;
  }
};

const downloadFile = (file: FileMetadata) => {
  window.open(`/api/v1/files/${file.id}/download`, '_blank');
};

const softDeleteFile = async (file: FileMetadata) => {
  if (!confirm(`Вы действительно хотите удалить файл "${file.filename}" (soft delete)?`)) return;
  try {
    await apiClient.delete(`/files/${file.id}`);
    fetchFiles();
  } catch (err: any) {
    alert(err.message || 'Ошибка удаления');
  }
};

const columns: DataTableColumns<FileMetadata> = [
  {
    title: 'Имя файла',
    key: 'filename',
    render(row) {
      return h('span', { style: 'font-weight: 600' }, row.filename);
    },
  },
  {
    title: 'MIME-тип (по сигнатуре)',
    key: 'mime_type',
    render(row) {
      return h(NTag, { size: 'small', bordered: false }, { default: () => row.mime_type });
    },
  },
  {
    title: 'Размер',
    key: 'size_bytes',
    render(row) {
      return `${(row.size_bytes / 1024).toFixed(1)} KB`;
    },
  },
  {
    title: 'Статус',
    key: 'status',
    render(row) {
      if (row.deleted_at) {
        return h(NTag, { type: 'error', size: 'small' }, { default: () => 'Удален (Soft-Delete)' });
      }
      return h(NTag, { type: 'success', size: 'small' }, { default: () => 'Активен' });
    },
  },
  {
    title: 'Дата',
    key: 'created_at',
    render(row) {
      return new Date(row.created_at).toLocaleString('ru-RU');
    },
  },
  {
    title: 'Действия',
    key: 'actions',
    render(row) {
      const btns = [];
      if (!row.deleted_at) {
        btns.push(
          h(
            NButton,
            {
              size: 'small',
              secondary: true,
              style: 'margin-right: 8px',
              onClick: () => downloadFile(row),
            },
            { default: () => 'Скачать' }
          )
        );
        btns.push(
          h(
            NButton,
            {
              size: 'small',
              type: 'error',
              secondary: true,
              onClick: () => softDeleteFile(row),
            },
            { default: () => 'Удалить' }
          )
        );
      } else {
        btns.push(h('span', { style: 'font-size: 12px; opacity: 0.5' }, 'Недоступен'));
      }
      return h('div', btns);
    },
  },
];

onMounted(() => {
  fetchFiles();
});
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
}

.page-subtitle {
  margin: 4px 0 0 0;
  font-size: 13px;
  opacity: 0.7;
}

.upload-hint {
  font-size: 12px;
  opacity: 0.7;
}
</style>
