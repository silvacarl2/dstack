package local

import (
	"context"
	"fmt"
	"io"
	"io/ioutil"
	"os"
	"path"
	"path/filepath"
	"strings"

	"github.com/dstackai/dstack/runner/consts"
	"github.com/dstackai/dstack/runner/internal/artifacts"
	"github.com/dstackai/dstack/runner/internal/artifacts/local"
	"github.com/dstackai/dstack/runner/internal/backend"
	"github.com/dstackai/dstack/runner/internal/common"
	"github.com/dstackai/dstack/runner/internal/gerrors"
	"github.com/dstackai/dstack/runner/internal/log"
	"github.com/dstackai/dstack/runner/internal/models"
	"github.com/dstackai/dstack/runner/internal/states"
	"gopkg.in/yaml.v3"
)

type File struct {
	Path string `yaml:"path"`
}

type Local struct {
	path      string
	runnerID  string
	state     *models.State
	storage   *LocalStorage
	cliSecret *ClientSecret
}

func init() {
	backend.DefaultBackend = New()
	backend.RegisterBackend("local", func(ctx context.Context, pathConfig string) (backend.Backend, error) {
		file := File{}
		theConfig, err := ioutil.ReadFile(pathConfig)
		if err != nil {
			fmt.Println("[ERROR]", err.Error())
			return nil, err
		}
		err = yaml.Unmarshal(theConfig, &file)
		if err != nil {
			fmt.Println("[ERROR]", err.Error())
			return nil, err
		}
		return New(), nil
	})
}

func New() *Local {
	path := filepath.Join(common.HomeDir(), consts.DSTACK_DIR_PATH)
	return &Local{
		path:      path,
		storage:   NewLocalStorage(path),
		cliSecret: NewClientSecret(path),
	}
}

func (l *Local) Init(ctx context.Context, ID string) error {
	log.Trace(ctx, "Initialize backend with ID runner", "runner ID", ID)
	l.runnerID = ID
	pathRunner := filepath.Join("runners", fmt.Sprintf("%s.yaml", ID))
	log.Trace(ctx, "Fetch local runner state", "path", pathRunner)
	contents, err := l.storage.GetFile(pathRunner)
	if err != nil {
		return gerrors.Wrap(err)
	}
	err = yaml.Unmarshal(contents, &l.state)
	if err != nil {
		return gerrors.Wrap(err)
	}
	return nil
}

func (l Local) Job(ctx context.Context) *models.Job {
	log.Trace(ctx, "Getting job from state", "ID", l.state.Job.JobID)
	return l.state.Job
}

func (l Local) MasterJob(ctx context.Context) *models.Job {
	contents, err := l.storage.GetFile(filepath.Join("jobs", l.state.Job.RepoUserName, l.state.Job.RepoName, fmt.Sprintf("%s.yaml", l.state.Job.MasterJobID)))
	if err != nil {
		return nil
	}
	masterJob := new(models.Job)
	err = yaml.Unmarshal(contents, masterJob)
	if err != nil {
		return nil
	}
	return masterJob
}

func (l Local) Requirements(ctx context.Context) models.Requirements {
	log.Trace(ctx, "Getting requirements")
	return l.state.Job.Requirements
}

func (l Local) UpdateState(ctx context.Context) error {
	log.Trace(ctx, "Start update state")
	log.Trace(ctx, "Marshaling job")
	contents, err := yaml.Marshal(&l.state.Job)
	if err != nil {
		return gerrors.Wrap(err)
	}
	jobPath := l.state.Job.JobFilepath()
	log.Trace(ctx, "Write to file job", "Path", jobPath)
	err = l.storage.PutFile(jobPath, contents)
	if err != nil {
		return gerrors.Wrap(err)
	}
	log.Trace(ctx, "Fetching list jobs", "Repo username", l.state.Job.RepoUserName, "Repo name", l.state.Job.RepoName, "Job ID", l.state.Job.JobID)
	files, err := l.storage.ListFile(l.state.Job.JobHeadFilepathPrefix())
	if err != nil {
		return gerrors.Wrap(err)
	}
	jobHeadFilepath := l.state.Job.JobHeadFilepath()
	for _, file := range files[:1] {
		log.Trace(ctx, "Renaming file job", "From", file, "To", jobHeadFilepath)
		err = l.storage.RenameFile(file, jobHeadFilepath)
		if err != nil {
			return gerrors.Wrap(err)
		}
	}
	return nil
}

func (l Local) CheckStop(ctx context.Context) (bool, error) {
	pathStateFile := fmt.Sprintf("runners/m;%s;status", l.runnerID)
	log.Trace(ctx, "Reading metadata from state file", "path", pathStateFile)
	if _, err := os.Stat(filepath.Join(l.path, pathStateFile)); err == nil {
		file, err := os.Open(filepath.Join(l.path, pathStateFile))
		if err != nil {
			return false, gerrors.Wrap(err)
		}
		body, err := io.ReadAll(file)
		if err != nil {
			return false, gerrors.Wrap(err)
		}
		if string(body) == states.Stopping {
			log.Trace(ctx, "Status equals stopping")
			return true, nil
		}
		log.Trace(ctx, "Metadata", "status", string(body))
		return false, nil
	}
	return false, nil
}

func (l Local) Shutdown(ctx context.Context) error {
	log.Trace(ctx, "Start shutdown")
	return nil
}

func (l *Local) GetArtifact(ctx context.Context, runName, localPath, remotePath string, _ bool) artifacts.Artifacter {
	rootPath := path.Join(common.HomeDir(), consts.USER_ARTIFACTS_PATH, runName)
	log.Trace(ctx, "Create simple artifact's engine. Local", "Root path", rootPath)
	art, err := local.NewLocal(l.path, rootPath, localPath, remotePath)
	if err != nil {
		log.Error(ctx, "Error create simple engine", "err", err)
		return nil
	}
	return art
}

func (l Local) CreateLogger(ctx context.Context, logGroup, logName string) io.Writer {
	log.Trace(ctx, "Build logger", "LogGroup", logGroup, "LogName", logName)
	logger, err := NewLogger(logGroup, logName)
	if err != nil {
		log.Error(ctx, "Failed create logger", "LogGroup", logGroup, "LogName", logName)
		return nil
	}
	return logger
}

func (l Local) GetJobByPath(ctx context.Context, path string) (*models.Job, error) {
	contents, err := l.storage.GetFile(path)
	if err != nil {
		return nil, gerrors.Wrap(err)
	}
	job := new(models.Job)
	if err = yaml.Unmarshal(contents, job); err != nil {
		return nil, gerrors.Wrap(err)
	}
	return job, nil
}

func (l *Local) GitCredentials(ctx context.Context) *models.GitCredentials {
	log.Trace(ctx, "Getting credentials")
	return l.cliSecret.fetchCredentials(ctx, l.state.Job.RepoHostNameWithPort(), l.state.Job.RepoUserName, l.state.Job.RepoName)
}

func (l *Local) Secrets(ctx context.Context) (map[string]string, error) {
	log.Trace(ctx, "Getting secrets")
	templatePath := fmt.Sprintf("secrets/%s/%s/%s", l.state.Job.RepoHostNameWithPort(), l.state.Job.RepoUserName, l.state.Job.RepoName)
	if _, err := os.Stat(filepath.Join(l.path, templatePath)); err != nil {
		return map[string]string{}, nil
	}
	listSecrets, err := os.ReadDir(filepath.Join(l.path, templatePath))
	if err != nil {
		return nil, gerrors.Wrap(err)
	}
	secrets := make(map[string]string, 0)
	for _, file := range listSecrets {
		if file.IsDir() {
			continue
		}
		if strings.HasPrefix(file.Name(), "l;") {
			clearName := strings.ReplaceAll(file.Name(), "l;", "")
			secrets[clearName] = fmt.Sprintf("%s/%s/%s/%s",
				l.state.Job.RepoHostNameWithPort(),
				l.state.Job.RepoUserName,
				l.state.Job.RepoName,
				clearName)
		}
	}
	return l.cliSecret.fetchSecret(ctx, templatePath, secrets)
}

func (l Local) Bucket(ctx context.Context) string {
	return ""
}

func (l Local) ListSubDir(ctx context.Context, dir string) ([]string, error) {
	log.Trace(ctx, "Fetching list sub dir")
	return l.storage.ListFile(dir)
}
