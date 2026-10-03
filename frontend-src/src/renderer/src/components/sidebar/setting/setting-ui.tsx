/* eslint-disable import/no-extraneous-dependencies */
import {
  Tabs,
  Button,
  DrawerRoot,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerBody,
  DrawerFooter,
  DrawerBackdrop,
  DrawerCloseTrigger,
} from "@chakra-ui/react";
import { useState, useMemo, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { CloseButton } from "@/components/ui/close-button";

import { settingStyles } from "./setting-styles";
import General from "./general";
import Live2D from "./live2d";
import ASR from "./asr";
import TTS from "./tts";
import Agent from "./agent";
import About from "./about";

interface SettingUIProps {
  open: boolean;
  onClose: () => void;
  onToggle: () => void;
}

function SettingUI({ open, onClose }: SettingUIProps): JSX.Element {
  const { t } = useTranslation();
  const [saveHandlers, setSaveHandlers] = useState<(() => void)[]>([]);
  const [cancelHandlers, setCancelHandlers] = useState<(() => void)[]>([]);
  const [activeTab, setActiveTab] = useState("general");

  const handleSaveCallback = useCallback((handler: () => void) => {
    setSaveHandlers((prev) => [...prev, handler]);
    return (): void => {
      setSaveHandlers((prev) => prev.filter((h) => h !== handler));
    };
  }, []);

  const handleCancelCallback = useCallback((handler: () => void) => {
    setCancelHandlers((prev) => [...prev, handler]);
    return (): void => {
      setCancelHandlers((prev) => prev.filter((h) => h !== handler));
    };
  }, []);

  const handleSave = useCallback((): void => {
    saveHandlers.forEach((handler) => handler());
    onClose();
  }, [saveHandlers, onClose]);

  const handleCancel = useCallback((): void => {
    cancelHandlers.forEach((handler) => handler());
    onClose();
  }, [cancelHandlers, onClose]);

  const tabsContent = useMemo(
    () => (
      <Tabs.ContentGroup>
        <Tabs.Content value="general" {...settingStyles.settingUI.tabs.content}>
          <General
            onSave={handleSaveCallback}
            onCancel={handleCancelCallback}
          />
        </Tabs.Content>
        <Tabs.Content value="asr" {...settingStyles.settingUI.tabs.content}>
          <ASR onSave={handleSaveCallback} onCancel={handleCancelCallback} />
        </Tabs.Content>
        <Tabs.Content
          value="advanced"
          {...settingStyles.settingUI.tabs.content}
        >
          <details>
            <summary style={{ cursor: "pointer", marginBottom: 16 }}>
              数字人显示参数
            </summary>
            <Live2D
              onSave={handleSaveCallback}
              onCancel={handleCancelCallback}
            />
          </details>
          <details>
            <summary style={{ cursor: "pointer", marginBottom: 16 }}>
              高级对话设置
            </summary>
            <Agent
              onSave={handleSaveCallback}
              onCancel={handleCancelCallback}
            />
          </details>
          <details>
            <summary style={{ cursor: "pointer", marginBottom: 16 }}>
              语音服务说明
            </summary>
            <TTS />
          </details>
          <details>
            <summary style={{ cursor: "pointer", marginBottom: 16 }}>
              项目来源
            </summary>
            <About />
          </details>
        </Tabs.Content>
      </Tabs.ContentGroup>
    ),
    [handleSaveCallback, handleCancelCallback],
  );

  return (
    <DrawerRoot
      open={open}
      onOpenChange={(e) => (e.open ? null : onClose())}
      placement="start"
    >
      <DrawerBackdrop />
      <DrawerContent {...settingStyles.settingUI.drawerContent}>
        <DrawerHeader {...settingStyles.settingUI.drawerHeader}>
          <DrawerTitle {...settingStyles.settingUI.drawerTitle}>
            {t("common.settings")}
          </DrawerTitle>
          <div {...settingStyles.settingUI.closeButton}>
            <DrawerCloseTrigger asChild onClick={handleCancel}>
              <CloseButton size="sm" color="white" />
            </DrawerCloseTrigger>
          </div>
        </DrawerHeader>

        <DrawerBody>
          <Tabs.Root
            defaultValue="general"
            value={activeTab}
            onValueChange={(details) => setActiveTab(details.value)}
            {...settingStyles.settingUI.tabs.root}
          >
            <Tabs.List {...settingStyles.settingUI.tabs.list}>
              <Tabs.Trigger
                value="general"
                {...settingStyles.settingUI.tabs.trigger}
              >
                显示
              </Tabs.Trigger>
              <Tabs.Trigger
                value="asr"
                {...settingStyles.settingUI.tabs.trigger}
              >
                语音
              </Tabs.Trigger>
              <Tabs.Trigger
                value="advanced"
                {...settingStyles.settingUI.tabs.trigger}
              >
                高级
              </Tabs.Trigger>
            </Tabs.List>

            {tabsContent}
          </Tabs.Root>
        </DrawerBody>

        <DrawerFooter>
          <Button colorPalette="red" onClick={handleCancel}>
            {t("common.cancel")}
          </Button>
          <Button colorPalette="blue" onClick={handleSave}>
            {t("common.save")}
          </Button>
        </DrawerFooter>
      </DrawerContent>
    </DrawerRoot>
  );
}

export default SettingUI;
