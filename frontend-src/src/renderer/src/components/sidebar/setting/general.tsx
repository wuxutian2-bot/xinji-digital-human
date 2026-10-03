/* eslint-disable import/no-extraneous-dependencies */
import { useTranslation } from "react-i18next";
import { Stack, createListCollection } from "@chakra-ui/react";
import { useBgUrl } from "@/context/bgurl-context";
import { settingStyles } from "./setting-styles";
import { useConfig } from "@/context/character-config-context";
import { useGeneralSettings } from "@/hooks/sidebar/setting/use-general-settings";
import { useWebSocket } from "@/context/websocket-context";
import { SelectField, SwitchField, InputField } from "./common";

interface GeneralProps {
  onSave?: (callback: () => void) => () => void;
  onCancel?: (callback: () => void) => () => void;
}

// Data collection definition
const useCollections = () => {
  const { backgroundFiles } = useBgUrl() || {};
  const { configFiles } = useConfig();

  const languages = createListCollection({
    items: [
      { label: "English", value: "en" },
      { label: "中文", value: "zh" },
    ],
  });

  const backgrounds = createListCollection({
    items:
      backgroundFiles?.map((filename) => ({
        label: String(filename),
        value: `/bg/${filename}`,
      })) || [],
  });

  const characterPresets = createListCollection({
    items: configFiles.map((config) => ({
      label: config.name,
      value: config.filename,
    })),
  });

  return {
    languages,
    backgrounds,
    characterPresets,
  };
};

function General({ onSave, onCancel }: GeneralProps): JSX.Element {
  const { t, i18n } = useTranslation();
  const bgUrlContext = useBgUrl();
  const { confName, setConfName } = useConfig();
  const { wsUrl, setWsUrl, baseUrl, setBaseUrl } = useWebSocket();
  const collections = useCollections();

  const {
    settings,
    handleSettingChange,
    handleCharacterPresetChange,
    showSubtitle,
    setShowSubtitle,
  } = useGeneralSettings({
    bgUrlContext,
    confName,
    setConfName,
    baseUrl,
    wsUrl,
    onWsUrlChange: setWsUrl,
    onBaseUrlChange: setBaseUrl,
    onSave,
    onCancel,
  });

  if (settings.language[0] !== i18n.language) {
    handleSettingChange("language", [i18n.language]);
  }

  return (
    <Stack {...settingStyles.common.container}>
      <SelectField
        label={t("settings.general.language")}
        value={settings.language}
        onChange={(value) => handleSettingChange("language", value)}
        collection={collections.languages}
        placeholder={t("settings.general.language")}
      />

      <SwitchField
        label={t("settings.general.showSubtitle")}
        checked={showSubtitle}
        onChange={setShowSubtitle}
      />

      <>
        <SelectField
          label={t("settings.general.backgroundImage")}
          value={settings.selectedBgUrl}
          onChange={(value) => handleSettingChange("selectedBgUrl", value)}
          collection={collections.backgrounds}
          placeholder={t("settings.general.backgroundImage")}
        />

        <InputField
          label={t("settings.general.customBgUrl")}
          value={settings.customBgUrl}
          onChange={(value) => handleSettingChange("customBgUrl", value)}
          placeholder={t("settings.general.customBgUrlPlaceholder")}
        />
      </>

      <details>
        <summary
          style={{ cursor: "pointer", color: "#aebfb3", marginBottom: 16 }}
        >
          高级连接设置
        </summary>
        <p style={{ fontSize: 12, color: "#aebfb3", marginBottom: 16 }}>
          更换服务或档案后，会显示对应档案的聊天记录。
        </p>
        <SelectField
          label={t("settings.general.characterPreset")}
          value={settings.selectedCharacterPreset}
          onChange={handleCharacterPresetChange}
          collection={collections.characterPresets}
          placeholder={confName || t("settings.general.characterPreset")}
        />

        <InputField
          label={t("settings.general.wsUrl")}
          value={settings.wsUrl}
          onChange={(value) => handleSettingChange("wsUrl", value)}
          placeholder="Enter WebSocket URL"
        />

        <InputField
          label={t("settings.general.baseUrl")}
          value={settings.baseUrl}
          onChange={(value) => handleSettingChange("baseUrl", value)}
          placeholder="Enter Base URL"
        />
      </details>
    </Stack>
  );
}

export default General;
