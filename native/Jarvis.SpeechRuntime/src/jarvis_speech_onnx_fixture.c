#include "jarvis_speech_onnx_fixture.h"

#include "onnxruntime_c_api.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static const OrtApi *fixture_api(const JarvisSpeechOnnxFixture *fixture) {
    return (const OrtApi *)fixture->api;
}

static void fixture_set_error(
    JarvisSpeechOnnxFixture *fixture,
    const char *message) {
    if (message == NULL) {
        fixture->last_error[0] = '\0';
        return;
    }
    (void)snprintf(
        fixture->last_error,
        sizeof(fixture->last_error),
        "%s",
        message);
}

static int fixture_runtime_error(
    JarvisSpeechOnnxFixture *fixture,
    OrtStatus *status) {
    const OrtApi *api = fixture_api(fixture);
    const char *message = "ONNX Runtime returned an unspecified error";
    if (api != NULL && status != NULL) {
        const char *runtime_message = api->GetErrorMessage(status);
        if (runtime_message != NULL) {
            message = runtime_message;
        }
    }
    fixture_set_error(fixture, message);
    if (api != NULL && status != NULL) {
        api->ReleaseStatus(status);
    }
    fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_FAULTED;
    return JARVIS_SPEECH_ONNX_FIXTURE_RUNTIME_ERROR;
}

static void fixture_release_runtime(JarvisSpeechOnnxFixture *fixture) {
    const OrtApi *api = fixture_api(fixture);
    if (api == NULL) {
        return;
    }
    if (fixture->session != NULL) {
        api->ReleaseSession((OrtSession *)fixture->session);
        fixture->session = NULL;
    }
    if (fixture->memory_info != NULL) {
        api->ReleaseMemoryInfo((OrtMemoryInfo *)fixture->memory_info);
        fixture->memory_info = NULL;
    }
    if (fixture->environment != NULL) {
        api->ReleaseEnv((OrtEnv *)fixture->environment);
        fixture->environment = NULL;
    }
}

int jarvis_speech_onnx_fixture_init(
    JarvisSpeechOnnxFixture *fixture,
    const void *model_data,
    size_t model_bytes) {
    const OrtApiBase *api_base;
    const OrtApi *api;
    OrtSessionOptions *options = NULL;
    OrtStatus *status;

    if (fixture == NULL || model_data == NULL || model_bytes == 0u) {
        return JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT;
    }
    memset(fixture, 0, sizeof(*fixture));
    fixture->abi_version = JARVIS_SPEECH_ONNX_FIXTURE_ABI_VERSION;
    fixture->struct_size = (uint32_t)sizeof(*fixture);

    api_base = OrtGetApiBase();
    if (api_base == NULL) {
        fixture_set_error(fixture, "OrtGetApiBase returned null");
        fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_FAULTED;
        return JARVIS_SPEECH_ONNX_FIXTURE_API_UNAVAILABLE;
    }
    api = api_base->GetApi(ORT_API_VERSION);
    if (api == NULL) {
        fixture_set_error(fixture, "ONNX Runtime C API version 31 is unavailable");
        fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_FAULTED;
        return JARVIS_SPEECH_ONNX_FIXTURE_API_UNAVAILABLE;
    }
    fixture->api = api;

    status = api->CreateEnv(
        ORT_LOGGING_LEVEL_WARNING,
        "jarvis-tiny-onnx-fixture",
        (OrtEnv **)&fixture->environment);
    if (status != NULL) {
        return fixture_runtime_error(fixture, status);
    }
    status = api->CreateSessionOptions(&options);
    if (status != NULL) {
        fixture_release_runtime(fixture);
        return fixture_runtime_error(fixture, status);
    }
    status = api->SetSessionExecutionMode(options, ORT_SEQUENTIAL);
    if (status == NULL) {
        status = api->SetIntraOpNumThreads(options, 1);
    }
    if (status == NULL) {
        status = api->SetInterOpNumThreads(options, 1);
    }
    if (status == NULL) {
        status = api->DisableCpuMemArena(options);
    }
    if (status == NULL) {
        status = api->DisableMemPattern(options);
    }
    if (status == NULL) {
        status = api->SetSessionGraphOptimizationLevel(
            options, ORT_ENABLE_BASIC);
    }
    if (status == NULL) {
        status = api->CreateSessionFromArray(
            (const OrtEnv *)fixture->environment,
            model_data,
            model_bytes,
            options,
            (OrtSession **)&fixture->session);
    }
    api->ReleaseSessionOptions(options);
    if (status != NULL) {
        fixture_release_runtime(fixture);
        return fixture_runtime_error(fixture, status);
    }
    status = api->CreateCpuMemoryInfo(
        OrtArenaAllocator,
        OrtMemTypeDefault,
        (OrtMemoryInfo **)&fixture->memory_info);
    if (status != NULL) {
        fixture_release_runtime(fixture);
        return fixture_runtime_error(fixture, status);
    }

    fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_READY;
    fixture_set_error(fixture, NULL);
    return JARVIS_SPEECH_ONNX_FIXTURE_OK;
}

int jarvis_speech_onnx_fixture_run(
    JarvisSpeechOnnxFixture *fixture,
    const float input[JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT],
    float output[JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT]) {
    const OrtApi *api;
    const char *input_names[] = {"x"};
    const char *output_names[] = {"y"};
    const OrtValue *inputs[1];
    OrtValue *input_value = NULL;
    OrtValue *output_value = NULL;
    OrtTensorTypeAndShapeInfo *shape_info = NULL;
    OrtStatus *status;
    ONNXTensorElementDataType element_type = ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED;
    int is_tensor = 0;
    int64_t shape[2] = {1, JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT};
    int64_t output_shape[2] = {0, 0};
    size_t dimension_count = 0u;
    size_t element_count = 0u;
    float input_copy[JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT];
    float *output_data = NULL;
    size_t index;
    int result = JARVIS_SPEECH_ONNX_FIXTURE_OK;

    if (fixture == NULL || input == NULL || output == NULL) {
        return JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT;
    }
    if (fixture->abi_version != JARVIS_SPEECH_ONNX_FIXTURE_ABI_VERSION ||
        fixture->struct_size != sizeof(*fixture) ||
        fixture->state != JARVIS_SPEECH_ONNX_FIXTURE_READY) {
        return JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE;
    }
    api = fixture_api(fixture);
    if (api == NULL || fixture->session == NULL || fixture->memory_info == NULL) {
        return JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE;
    }
    memcpy(input_copy, input, sizeof(input_copy));
    memset(output, 0, sizeof(float) * JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT);

    status = api->CreateTensorWithDataAsOrtValue(
        (const OrtMemoryInfo *)fixture->memory_info,
        input_copy,
        sizeof(input_copy),
        shape,
        2u,
        ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT,
        &input_value);
    if (status != NULL) {
        return fixture_runtime_error(fixture, status);
    }
    inputs[0] = input_value;
    status = api->Run(
        (OrtSession *)fixture->session,
        NULL,
        input_names,
        inputs,
        1u,
        output_names,
        1u,
        &output_value);
    if (status != NULL) {
        result = fixture_runtime_error(fixture, status);
        goto cleanup;
    }
    status = api->IsTensor(output_value, &is_tensor);
    if (status == NULL && is_tensor != 1) {
        fixture_set_error(fixture, "fixture output is not a tensor");
        fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_FAULTED;
        result = JARVIS_SPEECH_ONNX_FIXTURE_OUTPUT_INVALID;
        goto cleanup;
    }
    if (status == NULL) {
        status = api->GetTensorTypeAndShape(output_value, &shape_info);
    }
    if (status == NULL) {
        status = api->GetTensorElementType(shape_info, &element_type);
    }
    if (status == NULL) {
        status = api->GetDimensionsCount(shape_info, &dimension_count);
    }
    if (status == NULL && dimension_count == 2u) {
        status = api->GetDimensions(shape_info, output_shape, 2u);
    }
    if (status == NULL) {
        status = api->GetTensorShapeElementCount(shape_info, &element_count);
    }
    if (status != NULL) {
        result = fixture_runtime_error(fixture, status);
        goto cleanup;
    }
    if (element_type != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
        dimension_count != 2u || output_shape[0] != 1 ||
        output_shape[1] != JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT ||
        element_count != JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT) {
        fixture_set_error(fixture, "fixture output type or shape is invalid");
        fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_FAULTED;
        result = JARVIS_SPEECH_ONNX_FIXTURE_OUTPUT_INVALID;
        goto cleanup;
    }
    status = api->GetTensorMutableData(output_value, (void **)&output_data);
    if (status != NULL) {
        result = fixture_runtime_error(fixture, status);
        goto cleanup;
    }
    if (output_data == NULL) {
        fixture_set_error(fixture, "fixture output data is null");
        fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_FAULTED;
        result = JARVIS_SPEECH_ONNX_FIXTURE_OUTPUT_INVALID;
        goto cleanup;
    }
    for (index = 0u; index < JARVIS_SPEECH_ONNX_FIXTURE_ELEMENT_COUNT; ++index) {
        if (!isfinite(output_data[index])) {
            fixture_set_error(fixture, "fixture output contains a non-finite value");
            fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_FAULTED;
            result = JARVIS_SPEECH_ONNX_FIXTURE_OUTPUT_INVALID;
            goto cleanup;
        }
        output[index] = output_data[index];
    }
    fixture_set_error(fixture, NULL);

cleanup:
    if (shape_info != NULL) {
        api->ReleaseTensorTypeAndShapeInfo(shape_info);
    }
    if (output_value != NULL) {
        api->ReleaseValue(output_value);
    }
    if (input_value != NULL) {
        api->ReleaseValue(input_value);
    }
    return result;
}

int jarvis_speech_onnx_fixture_destroy(JarvisSpeechOnnxFixture *fixture) {
    if (fixture == NULL) {
        return JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT;
    }
    if (fixture->abi_version != JARVIS_SPEECH_ONNX_FIXTURE_ABI_VERSION ||
        fixture->struct_size != sizeof(*fixture) ||
        (fixture->state != JARVIS_SPEECH_ONNX_FIXTURE_READY &&
         fixture->state != JARVIS_SPEECH_ONNX_FIXTURE_FAULTED)) {
        return JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE;
    }
    fixture_release_runtime(fixture);
    fixture->api = NULL;
    fixture->state = JARVIS_SPEECH_ONNX_FIXTURE_DESTROYED;
    return JARVIS_SPEECH_ONNX_FIXTURE_OK;
}

const char *jarvis_speech_onnx_fixture_last_error(
    const JarvisSpeechOnnxFixture *fixture) {
    if (fixture == NULL) {
        return "invalid fixture";
    }
    return fixture->last_error;
}

const char *jarvis_speech_onnx_fixture_status_name(int status) {
    switch (status) {
        case JARVIS_SPEECH_ONNX_FIXTURE_OK:
            return "ok";
        case JARVIS_SPEECH_ONNX_FIXTURE_INVALID_ARGUMENT:
            return "invalid-argument";
        case JARVIS_SPEECH_ONNX_FIXTURE_INVALID_STATE:
            return "invalid-state";
        case JARVIS_SPEECH_ONNX_FIXTURE_API_UNAVAILABLE:
            return "api-unavailable";
        case JARVIS_SPEECH_ONNX_FIXTURE_RUNTIME_ERROR:
            return "runtime-error";
        case JARVIS_SPEECH_ONNX_FIXTURE_OUTPUT_INVALID:
            return "output-invalid";
        default:
            return "invalid";
    }
}
