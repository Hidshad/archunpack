from unittest.mock import MagicMock, patch
from archunpack.gui import ArchiveUnpackerGUI


@patch("tkinter.Tk")
@patch("tkinter.ttk.Style")
def test_gui_init(mock_style: MagicMock, mock_tk_cls: MagicMock) -> None:
    mock_tk = MagicMock()
    mock_tk_cls.return_value = mock_tk
    
    with patch("tkinter.ttk.Frame"), \
         patch("tkinter.ttk.Label"), \
         patch("tkinter.ttk.Entry"), \
         patch("tkinter.ttk.Button"), \
         patch("tkinter.ttk.Progressbar"), \
         patch("tkinter.ttk.Combobox"), \
         patch("tkinter.Spinbox"), \
         patch("tkinter.Label"), \
         patch("tkinter.Checkbutton"), \
         patch("tkinter.scrolledtext.ScrolledText"), \
         patch("archunpack.config.Config.detect_7zip", return_value=None), \
         patch("archunpack.config.Config.detect_winrar", return_value=None):
         
        gui = ArchiveUnpackerGUI(mock_tk)
        assert gui.root == mock_tk
        assert gui.background_thread is None
        assert gui.task_queue is None
        
        # Test file selection dialog triggers
        with patch("tkinter.filedialog.askdirectory", return_value="c:/some/dir"):
            gui.browse_source_dir()
            gui.entry_source.delete.assert_called()  # type: ignore[attr-defined]
            gui.entry_source.insert.assert_called_with(0, "c:\\some\\dir")  # type: ignore[attr-defined]
            
        with patch("tkinter.filedialog.askopenfilename", return_value="c:/some/file.zip"):
            gui.browse_source_file()
            gui.entry_source.delete.assert_called()  # type: ignore[attr-defined]
            gui.entry_source.insert.assert_called_with(0, "c:\\some\\file.zip")  # type: ignore[attr-defined]
            
        with patch("tkinter.filedialog.askdirectory", return_value="c:/out/dir"):
            gui.browse_output()
            gui.entry_output.delete.assert_called()  # type: ignore[attr-defined]
            gui.entry_output.insert.assert_called_with(0, "c:\\out\\dir")  # type: ignore[attr-defined]
            
        with patch("tkinter.filedialog.askopenfilename", return_value="c:/pw.txt"):
            gui.browse_pwd()
            gui.entry_pwd.delete.assert_called()  # type: ignore[attr-defined]
            gui.entry_pwd.insert.assert_called_with(0, "c:\\pw.txt")  # type: ignore[attr-defined]
